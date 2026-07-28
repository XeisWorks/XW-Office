"""Excel-exact presets and record builders for the five requested registers.

Ported from the "QR-Codes Online.xlsx" workbook analysis in
markdowns/QR_Code_Untermenue_PySide6_Spezifikation.md (sections 4, 6, 13, 31).

Two registers are named the opposite of what they compute in the workbook
("Ungerade Zahlen" yields the full 01-25 run, "Gerade Zahlen" yields only the
odd 01,03,...,25 run). This is reproduced verbatim on purpose and the
display names carry an explicit "(Excel-Logik: ...)" hint instead of silently
renaming or correcting the sequence.
"""
from __future__ import annotations

import string
from collections.abc import Sequence
from typing import Any

from xw_studio.services.qr_codes.filename_sanitizer import sanitize_windows_filename
from xw_studio.services.qr_codes.models import (
    GesamtspielchenRow,
    NumericSequenceSpec,
    QrConfigurationError,
    QrPresetError,
    QrRecord,
    QrVariantPreset,
)

WHOLE_SCALE = "whole_scale"
GESAMTSPIELCHEN = "gesamtspielchen"
UNGERADE_ZAHLEN_EXCEL = "ungerade_zahlen_excel"
GERADE_ZAHLEN_EXCEL = "gerade_zahlen_excel"
JEDE_4_ZAHL = "jede_4_zahl"

MAX_BATCH_SIZE = 10_000

_ALLOWED_PLACEHOLDERS = {
    "series_code",
    "project_slug",
    "instrument_slug",
    "instrument_upper",
    "number",
    "number_raw",
    "number_suffix",
    "id_suffix",
    "name",
    "slug",
    "ordinal",
}

GESAMTSPIELCHEN_DEFAULT_ROWS: tuple[GesamtspielchenRow, ...] = (
    GesamtspielchenRow(1, "Euphonium", "euph"),
    GesamtspielchenRow(2, "Begleitinstrumente", "begl"),
    GesamtspielchenRow(3, "Diatonische Harmonika", "harm"),
    GesamtspielchenRow(4, "B-Tuba", "btuba"),
    GesamtspielchenRow(5, "Flöte+Oboe+Violine", "in-c"),
    GesamtspielchenRow(6, "Saxophon", "sax"),
    GesamtspielchenRow(7, "Klarinette", "klar"),
    GesamtspielchenRow(8, "Tenorhorn", "ten"),
    GesamtspielchenRow(9, "F-Tuba", "ftuba"),
    GesamtspielchenRow(10, "Horn", "horn"),
    GesamtspielchenRow(11, "Posaune", "pos"),
    GesamtspielchenRow(12, "Trompete + Flügelhorn", "trp"),
)

INSTRUMENT_SUGGESTIONS: tuple[str, ...] = ("trp", "pos", "ftb", "btb", "hrn")

PRESETS: dict[str, QrVariantPreset] = {
    WHOLE_SCALE: QrVariantPreset(
        key=WHOLE_SCALE,
        display_name="Ganze Skala",
        generation_mode="numeric",
        id_template="{series_code}-{instrument_upper}/{number}",
        sequence=NumericSequenceSpec(start=1, end=111, step=1, minimum_width=2),
        base_path_template="/mh-player/p?e={project_slug}&i={instrument_slug}&t=",
        default_series_code="UUU#2",
        default_project_slug="uuu2",
        default_instrument_slug="pos",
        uses_canonical_router=True,
    ),
    GESAMTSPIELCHEN: QrVariantPreset(
        key=GESAMTSPIELCHEN,
        display_name="Gesamtspielchen",
        generation_mode="table",
        id_template="{ordinal:02d} {name}",
        table_rows=GESAMTSPIELCHEN_DEFAULT_ROWS,
        base_path_template="/dl-gesspiel/",
        legacy_note=(
            "Legacy-URL-Serie: nicht automatisch der kanonische Player-Router. "
            "Für Player-Track-Adressierung ist eine eigene Mapping-Tabelle nötig."
        ),
    ),
    UNGERADE_ZAHLEN_EXCEL: QrVariantPreset(
        key=UNGERADE_ZAHLEN_EXCEL,
        display_name="Ungerade Zahlen (Excel-Logik: 01–25)",
        generation_mode="numeric",
        id_template="{number}{id_suffix}",
        sequence=NumericSequenceSpec(start=1, end=25, step=1, minimum_width=2, number_suffix="d"),
        base_path_template="/loes-wu1-pos/",
        id_suffix="-LOESUNG",
        legacy_note="Legacy-URL-Serie (nicht der aktuelle Player-Router).",
    ),
    GERADE_ZAHLEN_EXCEL: QrVariantPreset(
        key=GERADE_ZAHLEN_EXCEL,
        display_name="Gerade Zahlen (Excel-Logik: 01, 03, …, 25)",
        generation_mode="numeric",
        id_template="{number}{id_suffix}",
        sequence=NumericSequenceSpec(start=1, end=25, step=2, minimum_width=2, number_suffix="d"),
        base_path_template="/wu1-check-trp/",
        id_suffix="-CHECK",
        legacy_note="Legacy-URL-Serie (nicht der aktuelle Player-Router).",
    ),
    JEDE_4_ZAHL: QrVariantPreset(
        key=JEDE_4_ZAHL,
        display_name="Jede 4. Zahl",
        generation_mode="numeric",
        id_template="{number}{id_suffix}",
        sequence=NumericSequenceSpec(start=4, end=24, step=4, minimum_width=2, number_suffix="d"),
        base_path_template="/wu1-clips-trp/",
        id_suffix="-CLIP",
        legacy_note="Legacy-URL-Serie (nicht der aktuelle Player-Router).",
    ),
}


def get_preset(variant_key: str) -> QrVariantPreset:
    preset = PRESETS.get(variant_key)
    if preset is None:
        raise QrPresetError(f"Unbekannte QR-Variante: {variant_key}")
    return preset


def generate_numbers(spec: NumericSequenceSpec) -> list[tuple[int, str]]:
    """Return (raw_number, zero_padded_display_number) pairs for one run.

    Numbers 01-09 keep their leading zero as text; 10+ are used as-is. The
    minimum_width setting must never truncate a longer number (100, 111, ...).
    """
    if spec.step <= 0:
        raise QrConfigurationError("Der Schritt muss größer als 0 sein.")
    if spec.end < spec.start:
        raise QrConfigurationError("Das Ende darf nicht kleiner als der Start sein.")
    count = (spec.end - spec.start) // spec.step + 1
    if count > MAX_BATCH_SIZE:
        raise QrConfigurationError(
            f"Diese Einstellung würde {count} Datensätze erzeugen. "
            f"Das Limit liegt bei {MAX_BATCH_SIZE}."
        )
    return [
        (n, f"{n:0{spec.minimum_width}d}{spec.number_suffix}")
        for n in range(spec.start, spec.end + 1, spec.step)
    ]


def _validate_template(template: str, *, field_name: str) -> set[str]:
    formatter = string.Formatter()
    try:
        fields = {name for _, name, _, _ in formatter.parse(template) if name}
    except ValueError as exc:
        raise QrConfigurationError(f"{field_name} enthält ein ungültiges Platzhalterformat.") from exc
    unknown = fields - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise QrConfigurationError(
            f"{field_name} enthält unbekannte Platzhalter: {', '.join(sorted(unknown))}"
        )
    return fields


def _render_template(template: str, values: dict[str, Any]) -> str:
    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError) as exc:
        raise QrConfigurationError(f"Muster konnte nicht angewendet werden: {exc}") from exc


class NumericQrFormData:
    """User-editable fields for one numeric-variant generation run."""

    __slots__ = (
        "series_code",
        "project_slug",
        "instrument_slug",
        "base_domain",
        "base_path_template",
        "id_template",
        "id_suffix",
        "sequence",
    )

    def __init__(
        self,
        *,
        series_code: str,
        project_slug: str,
        instrument_slug: str,
        base_domain: str,
        base_path_template: str,
        id_template: str,
        id_suffix: str,
        sequence: NumericSequenceSpec,
    ) -> None:
        self.series_code = series_code
        self.project_slug = project_slug
        self.instrument_slug = instrument_slug
        self.base_domain = base_domain
        self.base_path_template = base_path_template
        self.id_template = id_template
        self.id_suffix = id_suffix
        self.sequence = sequence


def default_numeric_form(preset: QrVariantPreset) -> NumericQrFormData:
    if preset.generation_mode != "numeric" or preset.sequence is None:
        raise QrPresetError(f"Variante '{preset.key}' ist keine numerische Serie.")
    return NumericQrFormData(
        series_code=preset.default_series_code,
        project_slug=preset.default_project_slug,
        instrument_slug=preset.default_instrument_slug,
        base_domain=preset.base_domain,
        base_path_template=preset.base_path_template,
        id_template=preset.id_template,
        id_suffix=preset.id_suffix,
        sequence=preset.sequence,
    )


def build_numeric_records(
    preset: QrVariantPreset,
    form: NumericQrFormData,
) -> tuple[QrRecord, ...]:
    """Build QrRecords for a numeric-run variant (Ganze Skala + the three legacy runs)."""
    _validate_template(form.id_template, field_name="ID-Muster")

    path_prefix = form.base_path_template.format(
        project_slug=form.project_slug,
        instrument_slug=form.instrument_slug,
    )
    records: list[QrRecord] = []
    for ordinal, (raw_number, display_number) in enumerate(generate_numbers(form.sequence), start=1):
        values = {
            "series_code": form.series_code,
            "project_slug": form.project_slug,
            "instrument_slug": form.instrument_slug,
            "instrument_upper": form.instrument_slug.upper(),
            "number": display_number,
            "number_raw": str(raw_number),
            "number_suffix": form.sequence.number_suffix,
            "id_suffix": form.id_suffix,
            "name": "",
            "slug": "",
            "ordinal": ordinal,
        }
        logical_id = _render_template(form.id_template, values)
        tail = str(raw_number) if preset.uses_canonical_router else display_number
        payload_url = f"{form.base_domain}{path_prefix}{tail}"
        records.append(
            QrRecord(
                ordinal=ordinal,
                source_key=display_number,
                logical_id=logical_id,
                payload_url=payload_url,
                output_filename=sanitize_windows_filename(logical_id) + ".png",
            )
        )
    return tuple(records)


def build_table_records(
    preset: QrVariantPreset,
    rows: Sequence[GesamtspielchenRow] | None = None,
) -> tuple[QrRecord, ...]:
    """Build QrRecords for the table-based "Gesamtspielchen" variant."""
    _validate_template(preset.id_template, field_name="ID-Muster")
    active_rows = tuple(rows) if rows is not None else preset.table_rows
    if not active_rows:
        raise QrConfigurationError("Die Tabelle enthält keine Zeilen.")

    path_prefix = preset.base_path_template.format(
        project_slug="",
        instrument_slug="",
    )
    records: list[QrRecord] = []
    for position, row in enumerate(active_rows, start=1):
        values = {
            "series_code": "",
            "project_slug": "",
            "instrument_slug": "",
            "instrument_upper": "",
            "number": "",
            "number_raw": "",
            "number_suffix": "",
            "id_suffix": preset.id_suffix,
            "name": row.display_name,
            "slug": row.slug,
            "ordinal": row.ordinal,
        }
        logical_id = _render_template(preset.id_template, values)
        payload_url = f"{preset.base_domain}{path_prefix}{row.slug}"
        records.append(
            QrRecord(
                ordinal=position,
                source_key=row.slug,
                logical_id=logical_id,
                payload_url=payload_url,
                output_filename=sanitize_windows_filename(logical_id) + ".png",
            )
        )
    return tuple(records)
