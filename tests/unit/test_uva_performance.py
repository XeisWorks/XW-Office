from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

import httpx
from xw_office.core.config import AppConfig
from xw_office.services.finanzonline.client import FinanzOnlineClient
from xw_office.services.finanzonline.uva_payload_service import UvaPayloadService
from xw_office.services.finanzonline.uva_preview import SevdeskUvaPreviewProvider, UvaPreviewService
from xw_office.services.finanzonline.uva_service import UvaService
from xw_office.services.finanzonline.uva_soap import MockUvaSoapBackend
from xw_office.services.finanzonline.zm_service import SevdeskZmInvoiceProvider, ZmService
from xw_office.services.http_client import SevdeskConnection


class _TaxSource:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.payment = "60.00"
        self.net = "100.00"
        self.uid = "DE136695976"
        self.old_date = "2026-08-01"
        self.purchase_tax = "20.00"
        self.purchase_label = "MIT 20% MEHRWERTSTEUER"

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] += 1
        if path == "/Invoice":
            return httpx.Response(200, json={"objects": [
                {
                    "id": "old", "invoiceNumber": "RE-OLD", "status": "750",
                    "invoiceDate": self.old_date, "paidDate": "2026-08-15",
                    "sumGross": "120.00", "sumNet": "100.00", "sumTax": "20.00",
                    "taxText": "MIT 20% MEHRWERTSTEUER", "contact": {"id": "domestic"},
                },
                {
                    "id": "eu", "invoiceNumber": "RE-EU", "status": "1000",
                    "invoiceDate": "2026-09-02", "paidDate": "2026-09-04",
                    "sumGross": self.net, "sumNet": self.net, "sumTax": "0.00",
                    "taxType": "eu", "taxRule": {"id": "3"},
                    "taxText": "STEUERFREIE INNERGEMEINSCHAFTL. LIEFERUNG (EU)",
                    "contact": {"id": "eu-contact"},
                },
            ]})
        if path == "/Invoice/old/getCheckAccountTransactionLogs":
            return httpx.Response(200, json={"objects": [{
                "checkAccountTransaction": {
                    "id": "tx", "valueDate": "2026-09-10",
                    "assignedAmountGross": self.payment,
                },
            }]})
        if path == "/Invoice/old/getCheckAccountTransactions":
            return httpx.Response(200, json={"objects": []})
        if path == "/InvoicePos":
            positions = [{
                "sumNetAccounting": self.net, "sumTaxAccounting": "0.00", "taxRate": "0",
            }] if request.url.params.get("invoice[id]") == "eu" else []
            return httpx.Response(200, json={"objects": positions})
        if path == "/Contact/eu-contact":
            return httpx.Response(200, json={"objects": [{
                "name": "EU Kunde", "vatNumber": self.uid,
            }]})
        if path == "/Voucher":
            return httpx.Response(200, json={"objects": [{
                "id": "purchase", "voucherNumber": "ER-1", "status": "1000",
                "voucherDate": "2026-09-02", "payDate": "2026-09-04",
                "creditDebit": "C", "sumNet": "100.00", "sumTax": self.purchase_tax,
                "sumGross": str(Decimal("100.00") + Decimal(self.purchase_tax)),
                "taxText": "0", "taxSet": {"id": "vat"},
            }]})
        if path == "/TaxSet/vat":
            return httpx.Response(200, json={"objects": [{"text": self.purchase_label}]})
        if path in {"/VoucherPos", "/CreditNote"}:
            return httpx.Response(200, json={"objects": []})
        raise AssertionError(f"Unexpected request: {path}")


def _service(
    connection: SevdeskConnection, *, reuse: bool
) -> UvaService:
    preview = UvaPreviewService(SevdeskUvaPreviewProvider(connection))
    return UvaService(
        AppConfig(),
        FinanzOnlineClient(AppConfig(), uva_backend=MockUvaSoapBackend()),
        preview_service=preview,
        payload_service=UvaPayloadService(preview),
        zm_service=ZmService(SevdeskZmInvoiceProvider(connection)),
        source_connection=connection if reuse else None,
    )


def test_run_reuse_preserves_full_tax_output_and_reduces_reads() -> None:
    source = _TaxSource()
    with httpx.Client(
        transport=httpx.MockTransport(source.handle), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        baseline = _service(connection, reuse=False).calculate_month(2026, 9)
        baseline_calls = source.calls.copy()
        source.calls.clear()
        progress: list[tuple[int, str]] = []
        optimized = _service(connection, reuse=True).calculate_month(
            2026, 9, progress=lambda value, text: progress.append((value, text))
        )

    assert {key: value for key, value in optimized.items() if key != "cache"} == {
        key: value for key, value in baseline.items() if key != "cache"
    }
    assert optimized["kennzahlen"]["A022"] == "50.00"
    assert optimized["zm"]["total_eur_int"] == 100
    assert any("Teilzahlung" in warning for warning in optimized["warnings"])
    assert source.calls["/InvoicePos"] == 2
    assert baseline_calls["/InvoicePos"] == 3
    assert sum(source.calls.values()) < sum(baseline_calls.values())
    assert source.calls["/Contact/domestic"] == 0
    assert optimized["cache"]["reused_requests"] == 1
    assert optimized["cache"]["source_requests"] == sum(source.calls.values())
    assert set(optimized["cache"]["phase_seconds"]) == {"preview", "kennzahlen", "zm"}
    assert [value for value, _ in progress] == sorted(value for value, _ in progress)
    assert any("ZM-Belege" in text for _, text in progress)
    assert any("API-Abfragen" in text for _, text in progress)


def test_refresh_reloads_payment_positions_and_contact_caches() -> None:
    source = _TaxSource()
    with httpx.Client(
        transport=httpx.MockTransport(source.handle), base_url="https://example.test"
    ) as client:
        connection = SevdeskConnection(client, AppConfig())
        service = _service(connection, reuse=True)
        first = service.calculate_month(2026, 9)
        calls = source.calls.copy()
        assert service.calculate_month(2026, 9)["cache"]["hit"] is True
        assert source.calls == calls
        source.payment = "30.00"
        source.net = "200.00"
        source.uid = "IT00743110157"
        source.purchase_tax = "10.00"
        source.purchase_label = "MIT 10% MEHRWERTSTEUER"
        refreshed = service.calculate_month(2026, 9, refresh=True)

    assert first["kennzahlen"]["A022"] == "50.00"
    assert refreshed["kennzahlen"]["A022"] == "25.00"
    assert refreshed["zm"]["total_eur_int"] == 200
    assert refreshed["zm"]["rows"][0]["uid"] == "IT00743110157"
    assert first["kennzahlen"]["C060"] == "20.00"
    assert refreshed["kennzahlen"]["C060"] == "10.00"
    assert source.calls["/InvoicePos"] == 4
    assert source.calls["/Contact/eu-contact"] == 2
    assert source.calls["/Invoice/old/getCheckAccountTransactionLogs"] == 2
    assert source.calls["/TaxSet/vat"] == 2
    assert source.calls["/VoucherPos"] == 2


def test_zm_skips_contact_reads_for_non_selected_documents() -> None:
    source = _TaxSource()
    source.old_date = "2026-09-03"
    with httpx.Client(
        transport=httpx.MockTransport(source.handle), base_url="https://example.test"
    ) as client:
        result = ZmService(
            SevdeskZmInvoiceProvider(SevdeskConnection(client, AppConfig()))
        ).calculate_month(2026, 9)

    assert result.considered == 2
    assert result.selected == 1
    assert result.total_eur_int == 100
    assert source.calls["/Contact/domestic"] == 0
    assert source.calls["/Contact/eu-contact"] == 1


def test_preview_progress_does_not_advance_on_timer(qtbot: Any) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QLabel, QProgressBar, QWidget

    from xw_office.core.worker import BackgroundWorker
    from xw_office.core.container import Container
    from xw_office.core.signals import AppSignals
    from xw_office.ui.modules.taxes.view import TaxesView

    class RunningWorker(BackgroundWorker):
        def isRunning(self) -> bool:
            return True

    view = TaxesView.__new__(TaxesView)
    QWidget.__init__(view)
    qtbot.addWidget(view)
    view._uva_preview_worker = RunningWorker(lambda: None)
    view._uva_submit_worker = None
    view._zm_prepare_worker = None
    view._uva_progress_bar = QProgressBar(view)
    view._uva_progress_bar.setValue(10)
    view._uva_progress_label = QLabel("UVA-Belege | 10 API-Abfragen", view)
    view._uva_progress_text = view._uva_progress_label.text()
    view._uva_progress_timer = QTimer(view)
    view._container = Container(AppConfig())
    view._container.register(AppSignals, lambda _: AppSignals())
    for _ in range(100):
        view._tick_uva_progress()
    assert view._uva_progress_bar.value() == 10
    assert view._uva_progress_label.text() == "UVA-Belege | 10 API-Abfragen"
    view._set_uva_progress(75, "ZM-Belege | 20 API-Abfragen")
    assert view._uva_progress_bar.maximum() == 0
    assert view._uva_progress_label.text() == "ZM-Belege | 20 API-Abfragen"
    view._set_uva_progress(100, "Abgeschlossen")
    assert view._uva_progress_bar.maximum() == 100
    assert view._uva_progress_bar.value() == 100
