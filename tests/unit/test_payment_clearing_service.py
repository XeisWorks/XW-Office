"""Deterministic payment-clearing service tests."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from xw_studio.core.config import AppConfig
from xw_studio.services.clearing.gateways import SevdeskClearingGateway, purpose_provider_ref
from xw_studio.services.clearing.models import (
    ClearingDuplicateKey,
    InvoiceRecord,
    MatchStatus,
    ProviderTransaction,
    ResetBatchResult,
    SevdeskTransaction,
    TransactionKind,
    money,
)
from xw_studio.services.clearing.service import PaymentClearingService
from xw_studio.services.http_client import SevdeskConnection

VIENNA = ZoneInfo("Europe/Vienna")


class _Provider:
    def __init__(self, rows: list[ProviderTransaction]) -> None:
        self.rows = rows

    def available(self) -> bool:
        return True

    def fetch(self, start: datetime, end: datetime) -> list[ProviderTransaction]:
        return self.rows


class _Wix:
    def available(self) -> bool:
        return True

    def provider_map(self, start: datetime, end: datetime) -> tuple[dict[str, str], dict]:
        return {"pi_1": "12345", "ch_1": "12345"}, {}


class _Sevdesk:
    def __init__(self) -> None:
        self.invoice = InvoiceRecord(7, "RE-100", "Wix | 12345", money("29.90"), 200, "Anna")
        self.created: list[dict] = []
        self.booked: list[dict] = []
        self.reset_calls: list[tuple[int, int]] = []
        self.existing: SevdeskTransaction | None = None
        self.transactions_by_account: dict[int, list[SevdeskTransaction]] = {}
        self.book_result: object = None

    def account_ids(self) -> dict[str, int]:
        return {"stripe": 11, "mollie": 12}

    def invoices(self, start: datetime, end: datetime) -> list[InvoiceRecord]:
        return [self.invoice]

    def transactions(self, account_id: int, start: datetime, end: datetime) -> list:
        return list(self.transactions_by_account.get(account_id, []))

    def get_check_account_transaction_by_id(self, transaction_id: int) -> dict[str, object]:
        for rows in self.transactions_by_account.values():
            for row in rows:
                if row.transaction_id == transaction_id:
                    return {"id": row.transaction_id, "status": row.status}
        return {"id": transaction_id, "status": 100}

    def change_check_account_transaction_status(self, transaction_id: int, status: int) -> dict[str, object]:
        self.reset_calls.append((transaction_id, status))
        for rows in self.transactions_by_account.values():
            for index, row in enumerate(rows):
                if row.transaction_id == transaction_id:
                    rows[index] = SevdeskTransaction(
                        row.transaction_id,
                        row.account_id,
                        row.amount,
                        row.value_date,
                        row.purpose,
                        status,
                    )
        return {"id": transaction_id, "status": status}

    def find_invoice(self, invoice_number: str) -> InvoiceRecord | None:
        return self.invoice if invoice_number == self.invoice.invoice_number else None

    def find_transaction_by_duplicate_key(
        self, account_id: int, duplicate_key: ClearingDuplicateKey, value_date: datetime
    ) -> SevdeskTransaction | None:
        if self.existing is None:
            return None
        expected = ClearingDuplicateKey(
            kind=TransactionKind.PAYMENT,
            provider="stripe",
            provider_ref="ch_1",
            value_date=self.existing.value_date.date().isoformat(),
            amount=self.existing.amount,
        )
        return self.existing if duplicate_key.as_tuple() == expected.as_tuple() else None

    def create_transaction(self, **kwargs: object) -> int:
        self.created.append(kwargs)
        return 99

    def book_invoice(self, **kwargs: object) -> object:
        self.booked.append(kwargs)
        return self.book_result


def _payment() -> ProviderTransaction:
    return ProviderTransaction(
        provider="stripe",
        provider_ref="ch_1",
        provider_order_id="pi_1",
        kind=TransactionKind.PAYMENT,
        amount=money("29.90"),
        created_at=datetime(2026, 5, 10, 12, 0, tzinfo=VIENNA),
        customer="Anna",
    )


def _service(sevdesk: _Sevdesk, rows: list[ProviderTransaction], tmp_path: Path) -> PaymentClearingService:
    return PaymentClearingService(
        stripe=_Provider(rows),  # type: ignore[arg-type]
        mollie=_Provider([]),  # type: ignore[arg-type]
        wix=_Wix(),  # type: ignore[arg-type]
        sevdesk=sevdesk,  # type: ignore[arg-type]
        history_dir=tmp_path,
    )


def test_money_is_decimal_and_rounded_to_cents() -> None:
    assert money("19,995") == Decimal("20.00")
    assert money(0.1 + 0.2) == Decimal("0.30")


def test_payout_purpose_is_idempotently_recognized() -> None:
    assert purpose_provider_ref("payout:stl_123 | 2026-03-01-2026-03-31 | PAYOUT") == "stl_123"


def test_sevdesk_gateway_book_invoice_uses_v2_book_amount_payload() -> None:
    calls: list[tuple[str, str]] = []
    invoice_reads = 0
    transaction_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal invoice_reads, transaction_reads
        path = request.url.path
        calls.append((request.method, path))
        if request.method == "GET" and path.endswith("/Invoice/7"):
            invoice_reads += 1
            status = 200 if invoice_reads == 1 else 1000
            return httpx.Response(200, json={"objects": {"id": 7, "status": status}})
        if request.method == "GET" and path.endswith("/CheckAccountTransaction/99"):
            transaction_reads += 1
            status = 100 if transaction_reads == 1 else 400
            return httpx.Response(
                200,
                json={"objects": {"id": 99, "status": status, "checkAccount": {"id": 11}}},
            )
        if request.method == "GET" and path.endswith("/Tools/bookkeepingSystemVersion"):
            return httpx.Response(200, json={"objects": {"version": "2.0"}})
        if request.method == "PUT" and path.endswith("/Invoice/7/bookAmount"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload == {
                "amount": 29.9,
                "date": 1783065600,
                "type": "FULL_PAYMENT",
                "checkAccount": {"id": 11, "objectName": "CheckAccount"},
                "checkAccountTransaction": {"id": 99, "objectName": "CheckAccountTransaction"},
                "createFeed": False,
            }
            return httpx.Response(200, json={"objects": {}})
        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test/api/v1",
    )
    gateway = SevdeskClearingGateway(SevdeskConnection(client=client, config=AppConfig()))

    result = gateway.book_invoice(
        invoice_id=7,
        amount=money("29.90"),
        payment_date=datetime(2026, 7, 3, 8, 0, tzinfo=ZoneInfo("UTC")),
        account_id=11,
        transaction_id=99,
    )

    assert result["status"] == "booked"
    assert ("PUT", "/api/v1/Invoice/7/bookAmount") in calls
    assert not any(path.endswith("/linkInvoice") for _method, path in calls)


def test_sevdesk_gateway_book_invoice_uses_legacy_link_invoice_patch_fallback() -> None:
    calls: list[tuple[str, str]] = []
    invoice_reads = 0
    transaction_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal invoice_reads, transaction_reads
        path = request.url.path
        calls.append((request.method, path))
        if request.method == "GET" and path.endswith("/Invoice/8"):
            invoice_reads += 1
            status = 200 if invoice_reads == 1 else 1000
            return httpx.Response(200, json={"objects": {"id": 8, "status": status}})
        if request.method == "GET" and path.endswith("/CheckAccountTransaction/88"):
            transaction_reads += 1
            status = 100 if transaction_reads == 1 else 400
            return httpx.Response(
                200,
                json={"objects": {"id": 88, "status": status, "checkAccount": {"id": 12}}},
            )
        if request.method == "GET" and path.endswith("/Tools/bookkeepingSystemVersion"):
            return httpx.Response(200, json={"objects": {"version": "1.0"}})
        if request.method == "PUT" and path.endswith("/CheckAccountTransaction/88/linkInvoice"):
            return httpx.Response(500, text="legacy put failed")
        if request.method == "PATCH" and path.endswith("/CheckAccountTransaction/88/linkInvoice"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload == {"amount": 29.9, "date": 1783065600}
            assert request.url.params["invoiceId"] == "8"
            return httpx.Response(200, json={"objects": {}})
        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test/api/v1",
    )
    gateway = SevdeskClearingGateway(SevdeskConnection(client=client, config=AppConfig()))

    result = gateway.book_invoice(
        invoice_id=8,
        amount=money("29.90"),
        payment_date=datetime(2026, 7, 3, 8, 0, tzinfo=ZoneInfo("UTC")),
        account_id=12,
        transaction_id=88,
    )

    assert result["status"] == "booked"
    assert ("PUT", "/api/v1/CheckAccountTransaction/88/linkInvoice") in calls
    assert ("PATCH", "/api/v1/CheckAccountTransaction/88/linkInvoice") in calls
    assert not any(path.endswith("/bookAmount") for _method, path in calls)


def test_analysis_preselects_exact_provider_wix_invoice_match(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    service = _service(sevdesk, [_payment()], tmp_path)

    analysis = service.analyze(date(2026, 5, 1), date(2026, 5, 31))

    assert analysis.ready_count == 1
    row = analysis.candidates[0]
    assert row.status == MatchStatus.READY
    assert row.selected is True
    assert row.order_number == "12345"
    assert row.invoice_number == "RE-100"
    assert analysis.run_id


def test_amount_mismatch_requires_manual_review(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.invoice = InvoiceRecord(7, "RE-100", "12345", money("30.00"), 200, "Anna")
    service = _service(sevdesk, [_payment()], tmp_path)

    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    assert row.status == MatchStatus.MANUAL
    assert row.selected is False
    assert "Betrag" in row.reason


def test_confirmed_batch_imports_then_books_once(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    result = service.book_selected([row])

    assert result.success_count == 1
    assert len(sevdesk.created) == 1
    assert len(sevdesk.booked) == 1
    assert sevdesk.booked[0]["transaction_id"] == 99
    assert len(list(tmp_path.glob("clearing_analysis_*.json"))) == 1
    assert len(list(tmp_path.glob("clearing_booking_*.json"))) == 1


def test_confirmed_batch_requires_confirmed_invoice_booking(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.book_result = {"status": "not_booked", "invoice_status": "200", "tx_status": "100"}
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    result = service.book_selected([row])

    assert result.failure_count == 1
    assert result.items[0].transaction_id == 99
    assert "status=not_booked" in result.items[0].message


def test_booking_recheck_does_not_import_when_invoice_is_now_paid(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]
    sevdesk.invoice = InvoiceRecord(7, "RE-100", "Wix | 12345", money("29.90"), 1000, "Anna")

    result = service.book_selected([row])

    assert result.success_count == 1
    assert result.items[0].status == MatchStatus.ALREADY_BOOKED
    assert sevdesk.created == []
    assert sevdesk.booked == []


def test_booking_rechecks_current_invoice_wix_order_before_writing(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]
    sevdesk.invoice = InvoiceRecord(7, "RE-100", "Wix | 99999", money("29.90"), 200, "Anna")

    result = service.book_selected([row])

    assert result.failure_count == 1
    assert "Wix-Order-Nr." in result.items[0].message
    assert sevdesk.created == []
    assert sevdesk.booked == []


def test_manual_invoice_assignment_requires_matching_wix_order(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.invoice = InvoiceRecord(7, "RE-100", "Wix | 99999", money("29.90"), 200, "Anna")
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    with pytest.raises(ValueError, match="Wix-Order-Nr."):
        service.assign_invoice(row, "RE-100")


def test_manual_invoice_assignment_normalizes_wix_order(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    assigned = service.assign_invoice(row, "RE-100")

    assert assigned.order_number == "12345"
    assert assigned.invoice_number == "RE-100"


def test_booking_reuses_existing_transaction_instead_of_importing_duplicate(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.existing = SevdeskTransaction(
        55,
        11,
        money("29.90"),
        datetime(2026, 5, 10, tzinfo=VIENNA),
        "order:12345 | stripe:ch_1 | PAYMENT",
        100,
    )
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    result = service.book_selected([row])

    assert result.success_count == 1
    assert sevdesk.created == []
    assert sevdesk.booked[0]["transaction_id"] == 55


def test_booking_does_not_reuse_same_ref_with_wrong_amount(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.existing = SevdeskTransaction(
        55,
        11,
        money("30.00"),
        datetime(2026, 5, 10, tzinfo=VIENNA),
        "order:12345 | stripe:ch_1 | PAYMENT",
        100,
    )
    service = _service(sevdesk, [_payment()], tmp_path)
    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    result = service.book_selected([row])

    assert result.success_count == 1
    assert len(sevdesk.created) == 1
    assert sevdesk.booked[0]["transaction_id"] == 99


def test_reset_transactions_in_range_only_resets_linked_entries(tmp_path: Path) -> None:
    sevdesk = _Sevdesk()
    sevdesk.transactions_by_account = {
        11: [
            SevdeskTransaction(1, 11, money("29.90"), datetime(2026, 6, 10, tzinfo=VIENNA), "a", 200),
            SevdeskTransaction(2, 11, money("29.90"), datetime(2026, 6, 11, tzinfo=VIENNA), "b", 100),
        ],
        12: [
            SevdeskTransaction(3, 12, money("29.90"), datetime(2026, 6, 12, tzinfo=VIENNA), "c", 200),
        ],
    }
    service = _service(sevdesk, [], tmp_path)

    result = service.reset_transactions_in_range(date(2026, 6, 1), date(2026, 6, 30))

    assert isinstance(result, ResetBatchResult)
    assert result.success_count == 2
    assert result.failure_count == 0
    assert sevdesk.reset_calls == [(1, 100), (3, 100)]
    assert sevdesk.transactions_by_account[11][0].status == 100
    assert sevdesk.transactions_by_account[11][1].status == 100
    assert sevdesk.transactions_by_account[12][0].status == 100


def test_refund_with_invoice_is_visible_but_not_preselected(tmp_path: Path) -> None:
    refund = ProviderTransaction(
        provider="stripe",
        provider_ref="re_1",
        provider_order_id="pi_1",
        kind=TransactionKind.REFUND,
        amount=money("-29.90"),
        created_at=datetime(2026, 5, 10, 12, 0, tzinfo=VIENNA),
        customer="Anna",
    )
    sevdesk = _Sevdesk()
    sevdesk.invoice = InvoiceRecord(7, "RE-100", "Wix | 12345", money("-29.90"), 200, "Anna")
    service = _service(sevdesk, [refund], tmp_path)

    row = service.analyze(date(2026, 5, 1), date(2026, 5, 31)).candidates[0]

    assert row.status == MatchStatus.REFUND_IMPORT
    assert row.selected is False
    assert row.is_bookable is True
    assert "Gutschrift" in row.reason
