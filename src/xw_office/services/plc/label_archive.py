"""Local archival of PLC PDF labels before they are sent to a printer."""

from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from threading import RLock

from xw_office.services.plc.customs_document import (
    customs_a5_print_path,
    ensure_customs_a5_print_file,
)
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
        self._customs_index_by_pair: dict[tuple[str, str], Path] = {}
        self._index_ready = False
        self._index_lock = RLock()

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

    def customs_print_path_for(self, shipment: PlcShipmentDraft) -> Path:
        """Return the persistent A5 derivative path without creating it."""
        return customs_a5_print_path(self.customs_path_for(shipment))

    def ensure_customs_print_document(self, shipment: PlcShipmentDraft) -> Path:
        """Create or refresh the calibrated A5 derivative from the PLC original."""
        original = self.find_customs_document(shipment)
        if original is None:
            raise FileNotFoundError(f"Archiviertes PLC-Zollformular fehlt: {self.customs_path_for(shipment)}")
        return ensure_customs_a5_print_file(original)

    def find_customs_print_document(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.customs_print_path_for(shipment)
        return candidate if candidate.is_file() else None

    def find_customs_document(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.customs_path_for(shipment)
        return candidate if candidate.is_file() else None

    def find_customs_for_invoice(
        self,
        *,
        order_reference: str,
        invoice_number: str,
        refresh: bool = True,
    ) -> Path | None:
        """Return the newest archived customs PDF for one order/invoice pair."""
        order = _safe_filename_part(order_reference, fallback="")
        invoice = _safe_filename_part(invoice_number, fallback="")
        if not order or not invoice:
            return None

        candidates: list[Path] = []
        exact = self._root / "customs" / f"{order} - {invoice} - Zollformular.pdf"
        if exact.is_file():
            candidates.append(exact)
        if refresh:
            self.refresh_index()
        with self._index_lock:
            indexed = self._customs_index_by_pair.get(
                (_strip_numeric_suffix(order), _strip_numeric_suffix(invoice))
            )
        if indexed is not None and indexed.is_file():
            candidates.append(indexed)

        if not candidates:
            return None
        candidates = list(dict.fromkeys(candidates))
        candidates.sort(key=_archive_recency_key, reverse=True)
        return candidates[0]

    def find(self, shipment: PlcShipmentDraft) -> Path | None:
        candidate = self.path_for(shipment)
        return candidate if candidate.is_file() else None

    def find_for_invoice(
        self,
        *,
        order_reference: str,
        invoice_number: str,
        refresh: bool = True,
    ) -> Path | None:
        """Return newest archived label for one order/invoice pair."""
        order = _safe_filename_part(order_reference, fallback="")
        invoice = _safe_filename_part(invoice_number, fallback="")
        if not order or not invoice:
            return None

        candidates: list[Path] = []
        exact = self._root / f"{order} - {invoice}.pdf"
        if exact.is_file():
            candidates.append(exact)

        if refresh:
            self.refresh_index()
        with self._index_lock:
            indexed = self._index_by_pair.get((_strip_numeric_suffix(order), _strip_numeric_suffix(invoice)))
        if indexed is not None and indexed.is_file():
            candidates.append(indexed)

        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]

    @property
    def index_ready(self) -> bool:
        with self._index_lock:
            return self._index_ready

    def refresh_index(self) -> tuple[int, int]:
        """Scan label/customs archive once; intended for a background worker."""
        labels: dict[tuple[str, str], Path] = {}
        customs: dict[tuple[str, str], Path] = {}
        if not self._root.exists() or not self._root.is_dir():
            with self._index_lock:
                self._index_by_pair = labels
                self._customs_index_by_pair = customs
                self._index_ready = True
            return 0, 0
        for file_path in self._root.glob("*.pdf"):
            pair = _label_pair(file_path)
            if pair is not None:
                _remember_newer(labels, pair, file_path)
        customs_root = self._root / "customs"
        if customs_root.is_dir():
            for file_path in customs_root.glob("*.pdf"):
                pair = _customs_pair(file_path)
                if pair is not None:
                    _remember_newer(customs, pair, file_path)
        with self._index_lock:
            self._index_by_pair = labels
            self._customs_index_by_pair = customs
            self._index_ready = True
        return len(labels), len(customs)


def _safe_filename_part(value: object, *, fallback: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text[:100] or fallback


def _strip_numeric_suffix(value: str) -> str:
    return re.sub(r"-\d{1,2}$", "", str(value or "").strip())


def _archive_recency_key(path: Path) -> tuple[int, int]:
    """Break equal Windows mtimes in favor of the later shipment suffix."""
    suffixes = [int(value) for value in re.findall(r"-(\d{1,2})(?=\s|$)", path.stem)]
    return (int(path.stat().st_mtime_ns), max(suffixes, default=0))


def _remember_newer(index: dict[tuple[str, str], Path], key: tuple[str, str], path: Path) -> None:
    current = index.get(key)
    if current is None or _archive_recency_key(path) > _archive_recency_key(current):
        index[key] = path


def _label_pair(path: Path) -> tuple[str, str] | None:
    if not path.is_file() or " - " not in path.stem:
        return None
    raw_order, raw_invoice = path.stem.split(" - ", 1)
    order = _strip_numeric_suffix(_safe_filename_part(raw_order, fallback=""))
    invoice = _strip_numeric_suffix(_safe_filename_part(raw_invoice, fallback=""))
    return (order, invoice) if order and invoice else None


def _customs_pair(path: Path) -> tuple[str, str] | None:
    suffix = " - Zollformular"
    if not path.is_file() or not path.stem.endswith(suffix):
        return None
    stem = path.stem[: -len(suffix)]
    if " - " not in stem:
        return None
    raw_order, raw_invoice = stem.split(" - ", 1)
    order = _strip_numeric_suffix(_safe_filename_part(raw_order, fallback=""))
    invoice = _strip_numeric_suffix(_safe_filename_part(raw_invoice, fallback=""))
    return (order, invoice) if order and invoice else None
