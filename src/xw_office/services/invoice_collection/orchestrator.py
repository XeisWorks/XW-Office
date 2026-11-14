"""Provider-independent collection orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Iterable

from xw_office.services.invoice_collection.domain import DocumentCandidate, DocumentOutcome
from xw_office.services.invoice_collection.journal import InvoiceJournal
from xw_office.services.invoice_collection.pipeline import DocumentPipeline, PipelineResult
from xw_office.services.invoice_collection.ports import CancelToken, InvoiceConnector


@dataclass(frozen=True)
class CollectionItemResult:
    source_id: str
    outcome: DocumentOutcome | None = None
    error: str | None = None
    route_key: str | None = None
    connection_id: str | None = None
    provider_id: str | None = None
    tenant_id: str | None = None
    account_alias: str | None = None
    display_name: str | None = None
    review_reason: str | None = None


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

    @property
    def review_count(self) -> int:
        return sum(item.review_reason is not None for item in self.items)

    @property
    def out_of_period_count(self) -> int:
        return sum(
            item.error is not None and item.error.startswith("OUT_OF_PERIOD:")
            for item in self.items
        )

    @property
    def error_count(self) -> int:
        return sum(
            item.error is not None and not item.error.startswith("OUT_OF_PERIOD:")
            for item in self.items
        )


class CollectionOrchestrator:
    """Run independent connectors through one pipeline without provider branches."""

    def __init__(
        self,
        pipeline: DocumentPipeline,
        workspace_root: Path | None = None,
        *,
        max_workers: int = 2,
        journal: InvoiceJournal | None = None,
        run_id: str | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.workspace_root = workspace_root
        self.max_workers = max(1, int(max_workers))
        self.journal = journal
        self.run_id = run_id

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
            try:
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
                                    connection_id=connection_id,
                                    error=_safe_error(exc),
                                    provider_id=getattr(connection, "provider_id", None),
                                    tenant_id=getattr(
                                        getattr(connection, "tenant_id", None), "value", None
                                    ),
                                    account_alias=getattr(connection, "account_alias", None),
                                )
                            )
                            continue
                        if not candidates:
                            results.append(
                                CollectionItemResult(
                                    source_id=connection_id,
                                    route_key=connector.route_key,
                                    connection_id=connection_id,
                                    provider_id=getattr(connection, "provider_id", None),
                                    tenant_id=getattr(
                                        getattr(connection, "tenant_id", None), "value", None
                                    ),
                                    account_alias=getattr(connection, "account_alias", None),
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
            finally:
                for connector in connector_list:
                    close = getattr(connector, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            # Cleanup failure must not mask the route result.
                            pass
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
                    connection_id = str(candidate.connection.connection_id)
                    if self.journal is not None and self.run_id is not None:
                        self.journal.record_checkpoint(
                            run_id=self.run_id,
                            connection_id=connection_id,
                            route_key=candidate.route_key,
                            source_id=candidate.source_id,
                        )
                    results.append(
                        CollectionItemResult(
                            source_id=candidate.source_id,
                            outcome=processed.receipt.outcome,
                            route_key=candidate.route_key,
                            connection_id=connection_id,
                            provider_id=candidate.connection.provider_id,
                            tenant_id=candidate.connection.tenant_id.value,
                            account_alias=candidate.connection.account_alias,
                            display_name=candidate.original_filename,
                            review_reason=processed.receipt.review_reason,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - continue independent providers
                    results.append(
                        CollectionItemResult(
                            source_id=candidate.source_id,
                            route_key=candidate.route_key,
                            connection_id=str(candidate.connection.connection_id),
                            error=_safe_error(exc),
                            provider_id=candidate.connection.provider_id,
                            tenant_id=candidate.connection.tenant_id.value,
                            account_alias=candidate.connection.account_alias,
                            display_name=candidate.original_filename,
                        )
                    )
        return results


def _safe_error(error: Exception) -> str:
    """Expose stable application errors without leaking arbitrary connector text."""
    from xw_office.services.invoice_collection.errors import InvoiceCollectionError

    if isinstance(error, InvoiceCollectionError):
        return f"{error.code.value}: {error}"
    return f"INTERNAL_ERROR: {type(error).__name__}"
