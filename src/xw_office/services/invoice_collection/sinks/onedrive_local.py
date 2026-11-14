"""No-clobber sink for a user-selected local OneDrive sync folder."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from xw_office.services.invoice_collection.domain import (
    DocumentOutcome,
    SinkReceipt,
    SyncStatus,
    ValidatedDocument,
)
from xw_office.services.invoice_collection.errors import DestinationError


class OneDriveLocalSink:
    """Publish validated PDFs locally and report synchronization as pending."""

    sink_id = "onedrive_local_sync"

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()

    def preflight(self) -> None:
        if not self.root.exists() or not self.root.is_dir():
            raise DestinationError("OneDrive-Zielordner ist nicht vorhanden")
        if not os.access(self.root, os.W_OK):
            raise DestinationError("OneDrive-Zielordner ist nicht beschreibbar")
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=".xw-preflight-", delete=True):
                pass
        except OSError as exc:
            raise DestinationError("OneDrive-Zielordner konnte nicht getestet werden") from exc

    def confirm_existing(self, relative_path: Path, sha256: str) -> SinkReceipt | None:
        """Confirm a journal-known target before suppressing a cross-route duplicate."""
        target = self._safe_target(relative_path)
        if not target.exists():
            return None
        existing_hash = _sha256(target)
        if existing_hash != sha256:
            raise DestinationError("Journalziel enthält einen abweichenden Inhalt")
        return SinkReceipt(
            outcome=DocumentOutcome.ALREADY_PRESENT,
            sync_status=SyncStatus.SYNC_PENDING,
            target_path=target,
            sha256=existing_hash,
        )

    def publish(self, document: ValidatedDocument, source_path: Path) -> SinkReceipt:
        self.preflight()
        target = self._safe_target(document.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing_hash = _sha256(target)
            if existing_hash == document.sha256:
                return SinkReceipt(
                    outcome=DocumentOutcome.ALREADY_PRESENT,
                    sync_status=SyncStatus.SYNC_PENDING,
                    target_path=target,
                    sha256=existing_hash,
                )
            raise DestinationError("Zieldatei mit abweichendem Inhalt vorhanden")

        try:
            temporary_handle = tempfile.NamedTemporaryFile(
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            )
            temporary = Path(temporary_handle.name)
            temporary_handle.close()
        except OSError as exc:
            raise DestinationError("Temporäre OneDrive-Datei konnte nicht erstellt werden") from exc
        try:
            shutil.copyfile(source_path, temporary)
            with temporary.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            if _sha256(temporary) != document.sha256:
                raise DestinationError("Prüfsumme des temporären Ziels stimmt nicht überein")
            try:
                os.link(temporary, target)
                temporary.unlink(missing_ok=True)
            except FileExistsError:
                return self._confirm_racing_target(target, document.sha256)
            except OSError:
                # Some sync filesystems do not support hard links.  O_EXCL still prevents
                # overwriting a pre-existing target, while the validated temp remains local.
                created_target = False
                try:
                    with temporary.open("rb") as source:
                        try:
                            target_handle = target.open("xb")
                        except FileExistsError:
                            return self._confirm_racing_target(target, document.sha256)
                        created_target = True
                        with target_handle as destination:
                            shutil.copyfileobj(source, destination)
                            destination.flush()
                            os.fsync(destination.fileno())
                    if _sha256(target) != document.sha256:
                        raise DestinationError("Prüfsumme des OneDrive-Ziels stimmt nicht überein")
                except BaseException as exc:
                    if created_target:
                        try:
                            target.unlink(missing_ok=True)
                        except OSError:
                            pass
                    if isinstance(exc, OSError):
                        raise DestinationError("OneDrive-Ziel konnte nicht vollständig geschrieben werden") from exc
                    raise
                temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return SinkReceipt(
            outcome=DocumentOutcome.NEW,
            sync_status=SyncStatus.SYNC_PENDING,
            target_path=target,
            sha256=document.sha256,
        )

    @staticmethod
    def _confirm_racing_target(target: Path, sha256: str) -> SinkReceipt:
        try:
            existing_hash = _sha256(target)
        except OSError as exc:
            raise DestinationError("Konkurrierendes OneDrive-Ziel konnte nicht geprüft werden") from exc
        if existing_hash != sha256:
            raise DestinationError("Konkurrierende Zieldatei enthält anderen Inhalt")
        return SinkReceipt(
            outcome=DocumentOutcome.ALREADY_PRESENT,
            sync_status=SyncStatus.SYNC_PENDING,
            target_path=target,
            sha256=existing_hash,
        )

    def _safe_target(self, relative_path: Path) -> Path:
        root = self.root.resolve(strict=False)
        target = (self.root / relative_path).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise DestinationError("Archivpfad verlässt den gewählten Zielordner") from exc
        if target.suffix.casefold() != ".pdf":
            raise DestinationError("Archivziel muss eine PDF-Datei sein")
        return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
