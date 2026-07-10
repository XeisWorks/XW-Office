from __future__ import annotations

from decimal import Decimal

from xw_studio.services.transfers.models import TransferPaymentData
from xw_studio.services.transfers.payment_qr import (
    PaymentQrError,
    create_epc_qr_from_payment_data,
    extract_payment_data_from_sources,
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
