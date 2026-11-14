"""Manual file import through the normal connector/pipeline contract."""
from __future__ import annotations

from pathlib import Path
import shutil

from xw_office.services.invoice_collection.domain import (
    DocumentCandidate,
    DocumentType,
    DownloadedArtifact,
    ProviderConnection,
)
from xw_office.services.invoice_collection.naming import workspace_download_path
from xw_office.services.invoice_collection.ports import CancelToken


class ManualImportConnector:
    """Treat user-selected files as candidates without writing to the archive."""

    route_key = "manual_import"

    def __init__(
        self,
        *,
        connection: ProviderConnection,
        files: list[Path],
        document_type: DocumentType = DocumentType.UNKNOWN,
    ) -> None:
        self.connection = connection
        self.files = tuple(path.expanduser() for path in files)
        self.document_type = document_type

    def discover(self) -> list[DocumentCandidate]:
        candidates: list[DocumentCandidate] = []
        for path in self.files:
            candidates.append(
                DocumentCandidate(
                    connection=self.connection,
                    route_key=self.route_key,
                    source_id=str(path.resolve(strict=False)),
                    external_id=None,
                    document_type=self.document_type,
                    original_filename=path.name,
                )
            )
        return candidates

    def download(
        self,
        candidate: DocumentCandidate,
        workspace: Path,
        cancel: CancelToken | None = None,
    ) -> DownloadedArtifact:
        if cancel is not None and cancel.cancelled:
            raise RuntimeError("Import abgebrochen")
        source = Path(candidate.source_id)
        workspace.mkdir(parents=True, exist_ok=True)
        destination = workspace_download_path(workspace, source.name)
        shutil.copy2(source, destination)
        return DownloadedArtifact(
            candidate=candidate, path=destination, content_type="application/pdf"
        )
