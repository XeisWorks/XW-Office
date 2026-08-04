"""Local archival of PLC PDF labels before they are sent to a printer."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from xw_office.services.plc.models import PlcShipmentDraft


class PlcLabelArchive:
    """Keep the exact PLC response PDF for reprints without a new shipment."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        configured = str(os.getenv("PLC_LABEL_ARCHIVE_DIR") or "").strip()
        root = (
            Path(root_dir)
            if root_dir is not None
            else Path(configured)
            if configured
            else self._default_root()
        )
        self._root = root.expanduser().resolve()
        self._index_by_pair: dict[tuple[str, str], Path] = {}
        self._index_snapshot: tuple[int, int] = (-1, -1)

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

    def customs_path_for(self, shipment: PlcShipmentDraft) -> Path:
        order = _safe_filename_part(shipment.reference, fallback="unbekannte-bestellung")
        invoice = _safe_filename_part(shipment.invoice_number, fallback="unbekannte-rechnung")
        return self._root / "customs" / f"{order} - {invoice} - Zollformular.pdf"

    def save_customs_document(self, shipment: PlcShipmentDraft, pdf_bytes: bytes) -> Path:
        """Archive the generated CN23 separately from the reprintable label."""
        if not bytes(pdf_bytes).startswith(b"%PDF-"):
            raise ValueError("PLC-Zollformulararchiv erwartet ein gültiges PDF")
        target = self.customs_path_for(shipment)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".tmp") as handle:
            handle.write(pdf_bytes)
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
        return target

    def find_customs_document(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.customs_path_for(shipment)
        return candidate if candidate.is_file() else None

    def find_customs_for_invoice(self, *, order_reference: str, invoice_number: str) -> Path | None:
        """Return the newest archived customs PDF for one order/invoice pair."""
        order = _safe_filename_part(order_reference, fallback="")
        invoice = _safe_filename_part(invoice_number, fallback="")
        if not order or not invoice:
            return None

        customs_root = self._root / "customs"
        if not customs_root.is_dir():
            return None

        candidates: list[Path] = []
        exact = customs_root / f"{order} - {invoice} - Zollformular.pdf"
        if exact.is_file():
            candidates.append(exact)

        expected_pair = (_strip_numeric_suffix(order), _strip_numeric_suffix(invoice))
        suffix = " - Zollformular"
        for file_path in customs_root.glob("*.pdf"):
            if not file_path.is_file() or not file_path.stem.endswith(suffix):
                continue
            pair_stem = file_path.stem[: -len(suffix)]
            if " - " not in pair_stem:
                continue
            raw_order, raw_invoice = pair_stem.split(" - ", 1)
            candidate_pair = (
                _strip_numeric_suffix(_safe_filename_part(raw_order, fallback="")),
                _strip_numeric_suffix(_safe_filename_part(raw_invoice, fallback="")),
            )
            if candidate_pair == expected_pair:
                candidates.append(file_path)

        if not candidates:
            return None
        candidates = list(dict.fromkeys(candidates))
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    def find(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.path_for(shipment)
        return candidate if candidate.is_file() else None

    def find_for_invoice(self, *, order_reference: str, invoice_number: str) -> Path | None:
        """Return newest archived label for one order/invoice pair."""
        order = _safe_filename_part(order_reference, fallback="")
        invoice = _safe_filename_part(invoice_number, fallback="")
        if not order or not invoice:
            return None

        candidates: list[Path] = []
        exact = self._root / f"{order} - {invoice}.pdf"
        if exact.is_file():
            candidates.append(exact)

        self._refresh_index_if_needed()
        indexed = self._index_by_pair.get((order, invoice))
        if indexed is not None and indexed.is_file():
            candidates.append(indexed)

        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    def _refresh_index_if_needed(self) -> None:
        if not self._root.exists() or not self._root.is_dir():
            self._index_by_pair = {}
            self._index_snapshot = (-1, -1)
            return
        root_stat = self._root.stat()
        snapshot = (int(root_stat.st_mtime_ns), int(root_stat.st_size))
        if snapshot == self._index_snapshot:
            return

        index: dict[tuple[str, str], Path] = {}
        for file_path in self._root.glob("*.pdf"):
            if not file_path.is_file():
                continue
            stem = file_path.stem
            if " - " not in stem:
                continue
            raw_order, raw_invoice = stem.split(" - ", 1)
            order = _safe_filename_part(raw_order, fallback="")
            invoice = _safe_filename_part(raw_invoice, fallback="")
            if not order or not invoice:
                continue
            key = (_strip_numeric_suffix(order), _strip_numeric_suffix(invoice))
            current = index.get(key)
            if current is None:
                index[key] = file_path
                continue
            if file_path.stat().st_mtime > current.stat().st_mtime:
                index[key] = file_path

        self._index_by_pair = index
        self._index_snapshot = snapshot


def _safe_filename_part(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:100] or fallback


def _strip_numeric_suffix(value: str) -> str:
    return re.sub(r"-\d{1,2}$", "", str(value or "").strip())
