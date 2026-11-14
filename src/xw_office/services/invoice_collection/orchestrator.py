"""Provider-independent collection orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Iterable

from xw_office.services.invoice_collection.domain import DocumentCandidate, DocumentOutcome
from xw_office.services.invoice_collection.pipeline import DocumentPipeline, PipelineResult
from xw_office.services.invoice_collection.ports import CancelToken, InvoiceConnector


@dataclass(frozen=True)
class CollectionItemResult:
    source_id: str
    outcome: DocumentOutcome | None = None
    error: str | None = None
    route_key: str | None = None


@dataclass(frozen=True)
class CollectionSummary:
    items: tuple[CollectionItemResult, ...] = ()
    cancelled: bool = False

    @property
    def new_count(self) -> int:
        return sum(item.outcome is DocumentOutcome.NEW for item in self.items)

    @property
    def existing_count(self) -> int:
        return sum(item.outcome is DocumentOutcome.ALREADY_PRESENT for item in self.items)


class CollectionOrchestrator:
    """Run independent connectors through one pipeline without provider branches."""

    def __init__(
        self,
        pipeline: DocumentPipeline,
        workspace_root: Path | None = None,
        *,
        max_workers: int = 2,
    ) -> None:
        self.pipeline = pipeline
        self.workspace_root = workspace_root
        self.max_workers = max(1, int(max_workers))

    def collect(
        self,
        connectors: Iterable[InvoiceConnector],
        *,
        cancel: CancelToken | None = None,
    ) -> CollectionSummary:
        results: list[CollectionItemResult] = []
        with tempfile.TemporaryDirectory(dir=self.workspace_root) as workspace:
            workspace_path = Path(workspace)
            connector_list = list(connectors)
            account_locks: dict[str, Lock] = {}
            futures = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for index, connector in enumerate(connector_list):
                    if cancel is not None and cancel.cancelled:
                        return CollectionSummary(tuple(results), cancelled=True)
                    connection = getattr(connector, "connection", None)
                    connection_id = str(getattr(connection, "connection_id", index))
                    lock = account_locks.setdefault(connection_id, Lock())
                    connector_workspace = workspace_path / str(index)
                    try:
                        candidates = connector.discover()
                    except Exception as exc:  # noqa: BLE001 - isolate a failed route
                        results.append(
                            CollectionItemResult(
                                source_id=connection_id,
                                route_key=connector.route_key,
                                error=_safe_error(exc),
                            )
                        )
                        continue
                    futures.append(
                        executor.submit(
                            self._collect_connector,
                            connector,
                            candidates,
                            connector_workspace,
                            cancel,
                            lock,
                        )
                    )
                for future in as_completed(futures):
                    results.extend(future.result())
        return CollectionSummary(tuple(results))

    def _collect_connector(
        self,
        connector: InvoiceConnector,
        candidates: list[DocumentCandidate],
        workspace: Path,
        cancel: CancelToken | None,
        account_lock: Lock,
    ) -> list[CollectionItemResult]:
        results: list[CollectionItemResult] = []
        with account_lock:
            for candidate in candidates:
                if cancel is not None and cancel.cancelled:
                    break
                try:
                    artifact = connector.download(candidate, workspace, cancel)
                    processed: PipelineResult = self.pipeline.process(artifact)
                    results.append(
                        CollectionItemResult(
                            source_id=candidate.source_id,
                            outcome=processed.receipt.outcome,
                            route_key=candidate.route_key,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - continue independent providers
                    results.append(
                        CollectionItemResult(
                            source_id=candidate.source_id,
                            route_key=candidate.route_key,
                            error=_safe_error(exc),
                        )
                    )
        return results


def _safe_error(error: Exception) -> str:
    """Expose stable application errors without leaking arbitrary connector text."""
    from xw_office.services.invoice_collection.errors import InvoiceCollectionError

    if isinstance(error, InvoiceCollectionError):
        return f"{error.code.value}: {error}"
    return f"INTERNAL_ERROR: {type(error).__name__}"
