"""Excel-compatibility tests: reproduce the workbook's exact ids, urls and counts.

See markdowns/QR_Code_Untermenue_PySide6_Spezifikation.md section 31.
"""
from __future__ import annotations

import pytest

from xw_office.services.qr_codes.models import GesamtspielchenRow, QrConfigurationError
from xw_office.services.qr_codes.presets import (
    GERADE_ZAHLEN_EXCEL,
    GESAMTSPIELCHEN,
    JEDE_4_ZAHL,
    UNGERADE_ZAHLEN_EXCEL,
    WHOLE_SCALE,
    build_numeric_records,
    build_table_records,
    default_numeric_form,
    get_preset,
)


def test_whole_scale_matches_excel_defaults() -> None:
    preset = get_preset(WHOLE_SCALE)
    records = build_numeric_records(preset, default_numeric_form(preset))

    assert len(records) == 111
    assert records[0].logical_id == "UUU#2-POS/01"
    assert records[0].payload_url == "https://www.xeisworks.at/mh-player/p?e=uuu2&i=pos&t=1"
    assert records[0].output_filename == "UUU#2-POS_01.png"

    assert records[-1].logical_id == "UUU#2-POS/111"
    assert records[-1].payload_url == "https://www.xeisworks.at/mh-player/p?e=uuu2&i=pos&t=111"
    assert records[-1].output_filename == "UUU#2-POS_111.png"


def test_gesamtspielchen_matches_excel_twelve_rows() -> None:
    preset = get_preset(GESAMTSPIELCHEN)
    records = build_table_records(preset)

    assert len(records) == 12
    assert records[0].logical_id == "01 Euphonium"
    assert records[0].payload_url == "https://www.xeisworks.at/dl-gesspiel/euph"
    assert records[-1].logical_id == "12 Trompete + Flügelhorn"
    assert records[-1].payload_url == "https://www.xeisworks.at/dl-gesspiel/trp"


def test_gesamtspielchen_accepts_custom_rows() -> None:
    preset = get_preset(GESAMTSPIELCHEN)
    custom = (GesamtspielchenRow(1, "Testinstrument", "test"),)
    records = build_table_records(preset, custom)

    assert len(records) == 1
    assert records[0].logical_id == "01 Testinstrument"
    assert records[0].payload_url == "https://www.xeisworks.at/dl-gesspiel/test"


def test_ungerade_zahlen_excel_logic_produces_full_01_to_25() -> None:
    """Despite its name, the Excel register produces the complete 01-25 run."""
    preset = get_preset(UNGERADE_ZAHLEN_EXCEL)
    records = build_numeric_records(preset, default_numeric_form(preset))

    assert len(records) == 25
    assert records[0].logical_id == "01d-LOESUNG"
    assert records[0].payload_url == "https://www.xeisworks.at/loes-wu1-pos/01d"
    assert records[-1].logical_id == "25d-LOESUNG"
    assert records[-1].payload_url == "https://www.xeisworks.at/loes-wu1-pos/25d"


def test_gerade_zahlen_excel_logic_produces_only_odd_numbers() -> None:
    """Despite its name, the Excel register produces only the odd 01,03,...,25 run."""
    preset = get_preset(GERADE_ZAHLEN_EXCEL)
    records = build_numeric_records(preset, default_numeric_form(preset))

    expected_ids = [f"{n:02d}d-CHECK" for n in range(1, 26, 2)]
    assert [r.logical_id for r in records] == expected_ids
    assert len(records) == 13
    assert records[0].payload_url == "https://www.xeisworks.at/wu1-check-trp/01d"
    assert records[-1].payload_url == "https://www.xeisworks.at/wu1-check-trp/25d"


def test_jede_4_zahl_matches_excel() -> None:
    preset = get_preset(JEDE_4_ZAHL)
    records = build_numeric_records(preset, default_numeric_form(preset))

    expected_ids = ["04d-CLIP", "08d-CLIP", "12d-CLIP", "16d-CLIP", "20d-CLIP", "24d-CLIP"]
    assert [r.logical_id for r in records] == expected_ids
    assert records[0].payload_url == "https://www.xeisworks.at/wu1-clips-trp/04d"
    assert records[-1].payload_url == "https://www.xeisworks.at/wu1-clips-trp/24d"


def test_unknown_id_template_placeholder_raises_configuration_error() -> None:
    preset = get_preset(WHOLE_SCALE)
    form = default_numeric_form(preset)
    form.id_template = "{not_a_real_placeholder}"

    with pytest.raises(QrConfigurationError):
        build_numeric_records(preset, form)


def test_editable_slugs_change_whole_scale_url_and_id() -> None:
    preset = get_preset(WHOLE_SCALE)
    form = default_numeric_form(preset)
    form.series_code = "OW#1"
    form.project_slug = "ow1"
    form.instrument_slug = "trp"

    records = build_numeric_records(preset, form)

    assert records[0].logical_id == "OW#1-TRP/01"
    assert records[0].payload_url == "https://www.xeisworks.at/mh-player/p?e=ow1&i=trp&t=1"
