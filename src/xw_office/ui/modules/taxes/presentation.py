"""Read-only presentation of the validated UVA preview and optional diagnostics."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xw_office.services.finanzonline.uva_preview import UvaPreviewResult, UvaPreviewSection


def format_euro(value: str) -> str:
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return value
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


def _amounts_html(vat: str, gross: str, net: str, *, title: str) -> str:
    rows = (
        (title, vat),
        ("Brutto", gross),
        ("Netto", net),
    )
    return "<table width='100%'>" + "".join(
        f"<tr><td>{escape(label)}</td><td align='right'>EUR {escape(format_euro(value))}</td></tr>"
        for label, value in rows
    ) + "</table>"


def _section_html(title: str, section: UvaPreviewSection) -> str:
    parts = [
        f"<h2>{title}</h2>",
        _amounts_html(section.total_vat, section.total_gross, section.total_net, title=title),
    ]
    for group in section.groups:
        parts.extend((
            f"<h3>{escape(group.label)}</h3>",
            _amounts_html(
                group.vat_amount, group.gross_amount, group.net_amount, title="Steuer"
            ),
        ))
    return "".join(parts)


def validate_preview(value: object) -> UvaPreviewResult | None:
    """Validate without modifying a snapshot or its FinanzOnline submission amounts."""
    if not isinstance(value, (dict, UvaPreviewResult)):
        return None
    try:
        return UvaPreviewResult.model_validate(value)
    except ValidationError:
        return None


def _count(value: object) -> int:
    try:
        return max(0, int(str(value or 0)))
    except (ValueError, TypeError):
        return 0


def blocker_status(data_quality: object) -> str:
    if not isinstance(data_quality, dict):
        return "Abgabestatus: noch nicht geprüft"
    blocking = data_quality.get("blocking")
    listed_count = len(blocking) if isinstance(blocking, list) else 0
    uva_count = _count(data_quality.get("uva_blocking_count"))
    zm_count = _count(data_quality.get("zm_blocking_count"))
    for key in ("uva_blocking", "zm_blocking"):
        entries = data_quality.get(key)
        if isinstance(entries, list):
            if key == "uva_blocking":
                uva_count = max(uva_count, len(entries))
            else:
                zm_count = max(zm_count, len(entries))
    count = max(_count(data_quality.get("blocking_count")), listed_count, uva_count + zm_count)
    if count:
        return f"Abgabe blockiert: {count} Blocker (UVA: {uva_count}, ZM: {zm_count})"
    status = str(data_quality.get("status") or "unbekannt")
    if status in ("blockiert", "ZM-UID pruefen", "ZM-UID prüfen"):
        return f"Abgabestatus: {status} – blockierende Prüfung erforderlich"
    labels = {"abgabebereit": "abgabebereit", "pruefen": "prüfen"}
    return f"Abgabestatus: {labels.get(status, status)} · 0 Blocker"


class CollapsibleDetails(QWidget):
    """A diagnostic section whose contents are hidden until explicitly requested."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.content = QPlainTextEdit()
        self.content.setReadOnly(True)
        self.content.setMaximumHeight(180)
        self.content.hide()
        self.toggle.toggled.connect(self._set_expanded)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)

    def _set_expanded(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)

    def set_text(self, text: str, *, count: int | None = None) -> None:
        self.toggle.setChecked(False)
        self.content.hide()
        self.content.setPlainText(text or "Keine Details vorhanden.")
        self.toggle.setText(self._title if count is None else f"{self._title} ({count})")


class UvaPresentation(QWidget):
    """VAT totals on the main surface; diagnostics remain collapsed by default."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("Abgabestatus: noch nicht geprüft")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.status)
        self.summary = QTextBrowser()
        self.summary.setOpenExternalLinks(False)
        self.summary.setPlainText("UVA berechnen, um Mehrwertsteuer und Vorsteuer zu sehen.")
        layout.addWidget(self.summary, 1)
        self.details: dict[str, CollapsibleDetails] = {}
        for key, title in (
            ("warnings", "Hinweise"),
            ("data_quality", "Datenqualität"),
            ("cache", "Technische Cache-Diagnose"),
            ("kennzahlen", "FinanzOnline-Kennzahlen"),
        ):
            detail = CollapsibleDetails(title)
            self.details[key] = detail
            layout.addWidget(detail)

    def set_preview(self, preview: UvaPreviewResult | None, data_quality: object) -> None:
        self.status.setText(blocker_status(data_quality))
        if preview is None:
            self.summary.setPlainText(
                "Keine gültige Steuervorschau vorhanden. Bitte UVA neu berechnen."
            )
            return
        self.summary.setHtml(
            _section_html("Mehrwertsteuer", preview.sales)
            + "<hr>"
            + _section_html("Vorsteuer", preview.input_tax)
        )
