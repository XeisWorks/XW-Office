import json
from pathlib import Path

from xw_studio.services.digital_licenses import DigitalLicenseService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrderItem


class _Invoices:
    def load_invoice_summaries(self, *, status: int | None, limit: int, offset: int) -> list[InvoiceSummary]:
        if status not in {100, 1000}:
            return []
        if status == 1000:
            return []
        return [
            InvoiceSummary(
                id="inv-1",
                invoiceNumber="RE-1",
                status=100,
                contact_name="Anna Example",
                order_reference="12345",
            )
        ]


class _Wix:
    def is_reference_manual_digital_license(self, reference: str, *, use_cache: bool = True) -> bool:
        assert use_cache is False
        return reference == "12345"

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {"wix_customer_name": "Anna Example", "wix_customer_email": "anna@example.test"}

    def fetch_order_line_items(self, reference: str) -> list[WixOrderItem]:
        return [
            WixOrderItem(sku="XW-1", name="Playable Piece", qty=1),
            WixOrderItem(sku="HANDLING", name="Digital Delivery Handling", qty=1),
        ]


class _WixCustom(_Wix):
    def fetch_order_line_items(self, reference: str) -> list[WixOrderItem]:
        return [WixOrderItem(sku="", name="Spezialarrangement", qty=1)]


class _WixRegularDigital(_Wix):
    def is_reference_manual_digital_license(self, reference: str, *, use_cache: bool = True) -> bool:
        assert use_cache is False
        return False


class _Catalog:
    def __init__(self, pdf: Path) -> None:
        self.pdf = pdf

    def resolve_sku(self, sku: str) -> object:
        return type("Product", (), {"print_file_path": str(self.pdf)})()

    def set_print_file_path(self, sku: str, path: str) -> None:
        self.pdf = Path(path)


class _Layout:
    pass


class _Secrets:
    def get_secret(self, key: str) -> str:
        return ""


class _Settings:
    def __init__(self, raw: str | None = None) -> None:
        self.raw = raw

    def get_value_json(self, key: str) -> str | None:
        return self.raw

    def set_value_json(self, key: str, value_json: str) -> None:
        self.raw = value_json


def _service(settings: _Settings, pdf: Path, wix: object | None = None) -> DigitalLicenseService:
    return DigitalLicenseService(
        invoices=_Invoices(),  # type: ignore[arg-type]
        wix_orders=wix or _Wix(),  # type: ignore[arg-type]
        catalog=_Catalog(pdf),  # type: ignore[arg-type]
        layout=_Layout(),  # type: ignore[arg-type]
        secret_service=_Secrets(),  # type: ignore[arg-type]
        settings_repo=settings,  # type: ignore[arg-type]
    )


def test_list_open_cases_ignores_handling_line(tmp_path: Path) -> None:
    pdf = tmp_path / "piece.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    cases = _service(_Settings(), pdf).list_open_cases()

    assert len(cases) == 1
    assert cases[0].customer_email == "anna@example.test"
    assert [line.name for line in cases[0].lines] == ["Playable Piece"]
    assert cases[0].lines[0].missing_print_file is False


def test_list_open_cases_skips_completed_invoice(tmp_path: Path) -> None:
    pdf = tmp_path / "piece.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    settings = _Settings(json.dumps({"inv-1": {"order_reference": "12345"}}))

    cases = _service(settings, pdf).list_open_cases()

    assert cases == []


def test_list_open_cases_keeps_custom_digital_line_without_sku(tmp_path: Path) -> None:
    pdf = tmp_path / "piece.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    cases = _service(_Settings(), pdf, wix=_WixCustom()).list_open_cases()

    assert len(cases) == 1
    assert cases[0].lines[0].sku == ""
    assert cases[0].lines[0].name == "Spezialarrangement"
    assert cases[0].lines[0].missing_print_file is True


def test_list_open_cases_ignores_regular_wix_digital_products(tmp_path: Path) -> None:
    pdf = tmp_path / "piece.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    cases = _service(_Settings(), pdf, wix=_WixRegularDigital()).list_open_cases()

    assert cases == []
