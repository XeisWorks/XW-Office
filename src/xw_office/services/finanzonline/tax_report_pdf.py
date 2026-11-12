"""Deterministic, secret-free tax report PDFs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import fitz  # type: ignore[import-untyped]


def render_uva_report(payload: dict[str, Any], *, reference: str = "", test_mode: bool = False) -> bytes:
    year_value = cast(int | str, payload.get("jahr") or payload.get("year"))
    month_value = cast(int | str, payload.get("monat") or payload.get("month"))
    year = int(year_value)
    month = int(month_value)
    lines = [
        "Umsatzsteuervoranmeldung U30", f"Periode: {month:02d}/{year}",
        f"Status: {'TEST – keine produktive Abgabe' if test_mode else 'Produktiv übermittelt'}",
        f"Übermittelt: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"FinanzOnline-Referenz: {reference or 'nicht vorhanden'}",
        f"Zahllast/Gutschrift: {payload.get('zahlbetrag') or '0.00'} EUR", "", "Kennzahlen:",
    ]
    for key, value in sorted((payload.get("kennzahlen") or {}).items()):
        lines.append(f"{key}: {value}")
    lines += ["", f"Regelversion: {payload.get('rule_version') or '-'}", "Erzeuger: XW-Office"]
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(54, 48, 540, 780), "\n".join(lines), fontsize=10, lineheight=1.35)
    output = cast(bytes, doc.tobytes())
    doc.close()
    return output


def render_u13_report(payload: dict[str, Any], *, reference: str = "", test_mode: bool = False) -> bytes:
    year_value = cast(int | str, payload.get("jahr") or payload.get("year"))
    month_value = cast(int | str, payload.get("monat") or payload.get("month"))
    year = int(year_value)
    month = int(month_value)
    rows = payload.get("rows") or []
    lines = [
        "Zusammenfassende Meldung U13",
        f"Periode: {month:02d}/{year}",
        f"Status: {'TEST – keine produktive Abgabe' if test_mode else 'Produktiv übermittelt'}",
        f"FinanzOnline-Referenz: {reference or 'nicht vorhanden'}",
        f"UID-Zeilen: {len(rows)}", "", "Meldungen:",
    ]
    for row in rows:
        if isinstance(row, dict):
            lines.append(f"{row.get('uid') or row.get('uidnr') or '-'} · {row.get('art') or '-'} · {row.get('betrag') or '0.00'} EUR")
    lines.append("Erzeuger: XW-Office")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(54, 48, 540, 780), "\n".join(lines), fontsize=10, lineheight=1.35)
    output = cast(bytes, doc.tobytes())
    doc.close()
    return output
