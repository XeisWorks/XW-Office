"""Provider-independent collection orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Iterable

from xw_office.services.invoice_collection.domain import DocumentOutcome
from xw_office.services.invoice_collection.pipeline import DocumentPipeline, PipelineResult
from xw_office.services.invoice_collection.ports import CancelToken, InvoiceConnector


@dataclass(frozen=True)
class CollectionItemResult:
    source_id: str
    outcome: DocumentOutcome | None = None
    error: str | None = None


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

    def __init__(self, pipeline: DocumentPipeline, workspace_root: Path | None = None) -> None:
        self.pipeline = pipeline
        self.workspace_root = workspace_root

    def collect(
        self,
        connectors: Iterable[InvoiceConnector],
        *,
        cancel: CancelToken | None = None,
    ) -> CollectionSummary:
        results: list[CollectionItemResult] = []
        with tempfile.TemporaryDirectory(dir=self.workspace_root) as workspace:
            workspace_path = Path(workspace)
            for connector in connectors:
                for candidate in connector.discover():
                    if cancel is not None and cancel.cancelled:
                        return CollectionSummary(tuple(results), cancelled=True)
                    try:
                        artifact = connector.download(candidate, workspace_path, cancel)
                        processed: PipelineResult = self.pipeline.process(artifact)
                        results.append(
                            CollectionItemResult(
                                source_id=candidate.source_id,
                                outcome=processed.receipt.outcome,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - continue independent providers
                        results.append(
                            CollectionItemResult(source_id=candidate.source_id, error=str(exc))
                        )
        return CollectionSummary(tuple(results))
