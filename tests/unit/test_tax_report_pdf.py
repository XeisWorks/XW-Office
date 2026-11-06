import fitz

from xw_office.services.finanzonline.tax_report_pdf import render_u13_report, render_uva_report


def _text(pdf: bytes) -> str:
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def test_uva_report_contains_snapshot_fields_and_test_marker() -> None:
    text = _text(render_uva_report({"jahr": 2026, "monat": 9, "zahlbetrag": "12.34", "kennzahlen": {"A000": "100.00"}}, reference="REF", test_mode=True))
    assert "Umsatzsteuervoranmeldung U30" in text
    assert "TEST" in text
    assert "REF" in text
    assert "12.34" in text


def test_u13_report_is_separate_and_has_uid_rows() -> None:
    text = _text(render_u13_report({"jahr": 2026, "monat": 9, "rows": [{"uid": "ATU123", "art": "L", "betrag": "10.00"}]}, reference="ZM-1"))
    assert "Zusammenfassende Meldung U13" in text
    assert "ATU123" in text
    assert "ZM-1" in text
    assert "Umsatzsteuervoranmeldung" not in text
