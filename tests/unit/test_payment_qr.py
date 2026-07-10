from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from xw_studio.services.transfers.models import TransferPaymentData
from xw_studio.services.transfers.payment_qr import (
    PaymentQrError,
    _extract_existing_epc_payload,
    _extract_pdf_text,
    create_epc_qr_from_payment_data,
    extract_payment_data_from_sources,
    _strip_json_fence,
)


def test_create_epc_qr_generates_png(tmp_path) -> None:
    payment = TransferPaymentData(
        recipient="XeisWorks GmbH",
        iban="AT611904300234573201",
        bic="BKAUATWW",
        amount=Decimal("12.34"),
        remittance_text="RE-2026-0042",
    )

    out = create_epc_qr_from_payment_data(payment, output_dir=tmp_path, filename_hint="invoice_42")

    assert out.exists()
    assert out.suffix.lower() == ".png"


def test_create_epc_qr_uses_structured_reference_for_plain_reference(tmp_path) -> None:
    import cv2

    payment = TransferPaymentData(
        recipient="LBG Burgenland Steuerberatung GmbH",
        iban="AT123200000000332189",
        bic="RLNWATWWXXX",
        amount=Decimal("34.20"),
        remittance_text="129973200353",
    )

    out = create_epc_qr_from_payment_data(payment, output_dir=tmp_path, filename_hint="hn_1299")
    image = cv2.imread(str(out))
    payload, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    lines = payload.splitlines()

    assert lines[9] == "129973200353"


def test_create_epc_qr_fails_without_valid_iban(tmp_path) -> None:
    payment = TransferPaymentData(
        recipient="XeisWorks GmbH",
        iban="INVALID",
        amount=Decimal("12.34"),
    )

    try:
        create_epc_qr_from_payment_data(payment, output_dir=tmp_path)
    except PaymentQrError:
        return

    raise AssertionError("PaymentQrError expected for invalid IBAN")


def test_extract_prefers_existing_epc_qr(monkeypatch) -> None:
    epc_payload = "\n".join(
        [
            "BCD",
            "002",
            "1",
            "SCT",
            "BKAUATWW",
            "XEISWORKS GMBH",
            "AT611904300234573201",
            "EUR123.45",
            "",
            "RE20260042",
            "RE-2026-0042",
        ]
    )

    monkeypatch.setattr(
        "xw_studio.services.transfers.payment_qr._extract_existing_epc_payload",
        lambda _pdf_bytes: epc_payload,
    )
    monkeypatch.setattr(
        "xw_studio.services.transfers.payment_qr._extract_pdf_text",
        lambda _pdf_bytes: "AT001234567890 Betrag 9,99",
    )

    payment = extract_payment_data_from_sources(
        pdf_bytes=b"dummy",
        use_openai_fallback=False,
    )

    assert payment.iban == "AT611904300234573201"
    assert payment.amount == Decimal("123.45")
    assert payment.remittance_text == "RE-2026-0042"
    assert payment.source_by_field["iban"].value == "pdf_existing_qr"


def test_extract_detects_beleg_original_qr_with_crlf_payload() -> None:
    pdf = Path("docs/invoices/Beleg_020-AR2604363 (1).pdf")
    assert pdf.exists()

    payload = _extract_existing_epc_payload(pdf.read_bytes())
    payment = extract_payment_data_from_sources(pdf_bytes=pdf.read_bytes(), use_openai_fallback=False)

    assert payload.startswith("BCD\n")
    assert payment.recipient == "BENEDIKTINERSTIFT ADMONT"
    assert payment.iban == "AT623821500007032402"
    assert payment.bic == "RZSTAT2G215"
    assert payment.amount == Decimal("988.44")
    assert payment.remittance_text == "020-AR2604363"
    assert payment.invoice_number == "020-AR2604363"
    assert payment.source_by_field["iban"].value == "pdf_existing_qr"


def test_extract_pdf_text_uses_pymupdf_footer_bank_data_for_beleg() -> None:
    pdf = Path("docs/invoices/Beleg_020-AR2604363 (1).pdf")
    assert pdf.exists()

    text = _extract_pdf_text(pdf.read_bytes())

    assert "IBAN" in text
    assert "AT623821500007032402" in text.replace(" ", "")
    assert "RZSTAT2G215" in text


def test_extract_wraps_pdf_bytes_for_pypdf(monkeypatch) -> None:
    seen: dict[str, bool] = {}

    class Reader:
        def __init__(self, source) -> None:
            seen["seekable"] = hasattr(source, "seek")
            self.pages = []

    monkeypatch.setattr("xw_studio.services.transfers.payment_qr.PdfReader", Reader)

    extract_payment_data_from_sources(pdf_bytes=b"%PDF", use_openai_fallback=False)

    assert seen["seekable"] is True


def test_extract_ignores_openai_fallback_failure(monkeypatch) -> None:
    def fail_openai(**_kwargs):
        raise RuntimeError("401 Unauthorized")

    monkeypatch.setattr("xw_studio.services.transfers.payment_qr._openai_fallback", fail_openai)

    payment = extract_payment_data_from_sources(
        mail_text="Bitte RE-123 bezahlen.",
        use_openai_fallback=True,
        openai_api_key="invalid",
    )

    assert isinstance(payment, TransferPaymentData)
    assert payment.invoice_number == "RE-123"


def test_extract_does_not_treat_rechnung_as_invoice_number() -> None:
    payment = extract_payment_data_from_sources(
        mail_text="Anbei sende ich dir die Rechnung fuer Juni 2026.",
        use_openai_fallback=False,
    )

    assert payment.invoice_number == ""


def test_extract_trims_iban_uses_labelled_bic_and_total_amount() -> None:
    payment = extract_payment_data_from_sources(
        mail_text=(
            "Rechnung\n"
            "Rechnungsdatum: 12.06.2026\n"
            "Bitte EUR 565,00 auf unser Konto AT233411000002623445 zu ueberweisen.\n"
            "IBAN: AT233411000002623445 BIC: RZOOAT2L110\n"
            "Gesamtbetrag EUR 565,00"
        ),
        use_openai_fallback=False,
    )

    assert payment.iban == "AT233411000002623445"
    assert payment.bic == "RZOOAT2L110"
    assert payment.amount == Decimal("565.00")


def test_extract_ignores_unlabelled_bic_like_words() -> None:
    payment = extract_payment_data_from_sources(
        mail_text="RECHNUNG\nGesamtbetrag EUR 70,00\nIBAN: AT75 2081 5090 0000 6628",
        use_openai_fallback=False,
    )

    assert payment.bic == ""


def test_openai_payload_can_override_weak_pdf_text(monkeypatch) -> None:
    def fake_openai(**_kwargs):
        return {
            "recipient": "Kulturkreis Gallenstein",
            "iban": "AT752081509000006628",
            "bic": "STSPAT2GXXX",
            "amount": "70,00",
            "remittance_text": "199/1820",
            "invoice_number": "199/1820",
        }

    monkeypatch.setattr("xw_studio.services.transfers.payment_qr._openai_fallback", fake_openai)

    payment = extract_payment_data_from_sources(
        mail_text=(
            "Festival St. Gallen Steiermark\n"
            "Bernhard Holl\n"
            "Gesamtpreis EUR 70,00\n"
            "IBAN: AT75 2081 5090 0000 6628\n"
            "Verwendungszweck: 199/1820"
        ),
        use_openai_fallback=True,
        openai_api_key="key",
    )

    assert payment.recipient == "Kulturkreis Gallenstein"
    assert payment.amount == Decimal("70.00")
    assert payment.remittance_text == "199/1820"
    assert payment.source_by_field["recipient"].value == "openai"


def test_invoice_number_wins_over_generic_openai_remittance(monkeypatch) -> None:
    def fake_openai(**_kwargs):
        return {
            "recipient": "Yannick Herzog IT Services",
            "iban": "DE92500105175420129425",
            "bic": "INGDDEFFXXX",
            "amount": "495,00",
            "remittance_text": "Rechnung Juni 2026",
            "invoice_number": "RE-241665",
        }

    monkeypatch.setattr("xw_studio.services.transfers.payment_qr._openai_fallback", fake_openai)

    payment = extract_payment_data_from_sources(
        mail_text="WG: Rechnung Juni 2026",
        use_openai_fallback=True,
        openai_api_key="key",
    )

    assert payment.invoice_number == "RE-241665"
    assert payment.remittance_text == "RE-241665"


def test_invoice_number_wins_over_labelled_openai_remittance(monkeypatch) -> None:
    def fake_openai(**_kwargs):
        return {
            "recipient": "Yannick Herzog IT Services",
            "iban": "DE92500105175420129425",
            "bic": "INGDDEFFXXX",
            "amount": "495,00",
            "remittance_text": "Rechnung Nr. RE-241665",
            "invoice_number": "RE-241665",
        }

    monkeypatch.setattr("xw_studio.services.transfers.payment_qr._openai_fallback", fake_openai)

    payment = extract_payment_data_from_sources(
        mail_text="WG: Rechnung Juni 2026",
        use_openai_fallback=True,
        openai_api_key="key",
    )

    assert payment.remittance_text == "RE-241665"


def test_strip_json_fence_for_openai_response() -> None:
    raw = '```json\n{"recipient": "HÖRBST", "amount": "565,00"}\n```'

    assert _strip_json_fence(raw) == '{"recipient": "HÖRBST", "amount": "565,00"}'
