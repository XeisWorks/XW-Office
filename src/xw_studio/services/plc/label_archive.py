"""Local archival of PLC PDF labels before they are sent to a printer."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from xw_studio.services.plc.models import PlcShipmentDraft


class PlcLabelArchive:
    """Keep the exact PLC response PDF for reprints without a new shipment."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        configured = str(os.getenv("PLC_LABEL_ARCHIVE_DIR") or "").strip()
        root = Path(root_dir) if root_dir is not None else Path(configured) if configured else self._default_root()
        self._root = root.expanduser().resolve()

    @staticmethod
    def _default_root() -> Path:
        # Keep reprintable labels next to the existing application state, not
        # in the temporary directory which the print queue cleans up.
        return Path(__file__).resolve().parents[4] / "state" / "plc_labels"

    def path_for(self, shipment: PlcShipmentDraft) -> Path:
        order = _safe_filename_part(shipment.reference, fallback="unbekannte-bestellung")
        invoice = _safe_filename_part(shipment.invoice_number, fallback="unbekannte-rechnung")
        # Windows does not permit a pipe character in filenames. A dash keeps
        # the requested order/invoice association human-readable.
        return self._root / f"{order} - {invoice}.pdf"

    def save(self, shipment: PlcShipmentDraft, pdf_bytes: bytes) -> Path:
        if not bytes(pdf_bytes).startswith(b"%PDF-"):
            raise ValueError("PLC-Labelarchiv erwartet ein gültiges PDF")
        target = self.path_for(shipment)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as handle:
            handle.write(pdf_bytes)
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        return target

    def find(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.path_for(shipment)
        return candidate if candidate.is_file() else None


def _safe_filename_part(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:100] or fallback
