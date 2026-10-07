"""Clearing safety gates, durable checkpoints and cooperative cancellation."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository
from xw_office.services.clearing.booking_store import ClearingBookingStore
from xw_office.services.clearing.models import (
    ClearingCandidate,
    InvoiceRecord,
    MatchStatus,
    ProviderTransaction,
    SevdeskTransaction,
    TransactionKind,
)
from xw_office.services.clearing.service import PaymentClearingService, _order_number

TZ = ZoneInfo("Europe/Vienna")
DATE = datetime(2026, 9, 10, tzinfo=TZ)


class _MemoryRepo:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def set_value_json(self, key: str, value: str) -> None:
        self.values[key] = value

    def mutate_value_json(self, key: str, fn: Callable[[str | None], str]) -> str:
        value = fn(self.values.get(key))
        self.values[key] = value
        return value


def _row(ref: str = "tr_1", kind: TransactionKind = TransactionKind.PAYMENT) -> ClearingCandidate:
    return ClearingCandidate(
        candidate_id=ref, provider="mollie", provider_ref=ref, kind=kind,
        order_number="12345" if kind == TransactionKind.PAYMENT else "",
        invoice_id=7 if kind == TransactionKind.PAYMENT else None,
        invoice_number="RE-1" if kind == TransactionKind.PAYMENT else "",
        customer="Test", amount=Decimal("50") if kind == TransactionKind.PAYMENT else Decimal("-50"),
        payment_date=DATE, status=MatchStatus.READY if kind == TransactionKind.PAYMENT else MatchStatus.IMPORT_ONLY,
        reason="Test", selected=True, account_id=12,
    )


def _gateway() -> MagicMock:
    gateway = MagicMock()
    gateway.account_ids.return_value = {"stripe": 11, "mollie": 12}
    gateway.transactions.return_value = []
    invoice = InvoiceRecord(7, "RE-1", "12345", Decimal("50"), 200, "Test")
    gateway.find_invoice.return_value = invoice
    gateway.invoices.return_value = [invoice]
    gateway.create_transaction.return_value = 99
    gateway.book_invoice.return_value = {"status": "booked"}
    return gateway


def _service(
    tmp_path: Path, gateway: MagicMock, repo: _MemoryRepo | None = None
) -> PaymentClearingService:
    return PaymentClearingService(
        settings_repo=repo,  # type: ignore[arg-type]
        sevdesk=gateway, history_dir=tmp_path,
    )


@pytest.mark.parametrize("text", ["12345 und 67890", "Wix 12345 / 67890"])
def test_order_parser_rejects_multiple_distinct_numbers(text: str) -> None:
    assert _order_number(text) == ""
    assert _order_number("Wix 12345, nochmal 12345") == "12345"


def test_booking_checkpoint_survives_repository_restart(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    SettingKV.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    row = _row()
    first = ClearingBookingStore(SettingKvRepository(factory))
    reservation = first.claim(row)
    first.checkpoint(row, reservation, state="imported", transaction_id=99)

    restarted = ClearingBookingStore(SettingKvRepository(factory))
    with pytest.raises(RuntimeError, match="unklar"):
        restarted.claim(row)
    restarted.checkpoint(row, reservation, state="completed", transaction_id=99)
    assert restarted.claim(row).transaction_id == 99
    engine.dispose()


def test_draft_rejected_at_assignment_and_booking(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.find_invoice.return_value = InvoiceRecord(7, "RE-1", "12345", Decimal("50"), 100, "Test")
    service = _service(tmp_path, gateway)
    with pytest.raises(ValueError, match="Entwurf"):
        service.assign_invoice(_row(), "RE-1")
    result = service.book_selected([_row()])
    assert result.failure_count == 1
    gateway.create_transaction.assert_not_called()
    gateway.book_invoice.assert_not_called()


def test_duplicate_payout_in_batch_is_only_imported_once(tmp_path: Path) -> None:
    gateway = _gateway()
    service = _service(tmp_path, gateway)
    row = _row("po_1", TransactionKind.PAYOUT)
    result = service.book_selected([row, row])
    assert result.success_count == 1
    assert gateway.create_transaction.call_count == 1


def test_same_id_with_conflicting_amounts_in_batch_is_blocked(tmp_path: Path) -> None:
    gateway = _gateway()
    service = _service(tmp_path, gateway)
    row = _row("po_1", TransactionKind.PAYOUT)
    result = service.book_selected([row, replace(row, amount=Decimal("-60"))])
    assert result.failure_count == 1
    gateway.create_transaction.assert_not_called()


def test_existing_provider_id_with_different_amount_is_not_reimported(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.transactions.return_value = [
        SevdeskTransaction(55, 12, Decimal("60"), DATE, "mollie:tr_1 | PAYMENT", 100)
    ]
    result = _service(tmp_path, gateway).book_selected([_row()])
    assert result.failure_count == 1
    gateway.create_transaction.assert_not_called()
    gateway.book_invoice.assert_not_called()


def test_lost_transaction_id_is_not_silently_reused(tmp_path: Path) -> None:
    gateway = _gateway()
    result = _service(tmp_path, gateway).book_selected([replace(_row(), transaction_id=55)])
    assert result.failure_count == 1
    gateway.create_transaction.assert_not_called()
    gateway.book_invoice.assert_not_called()


def test_reset_never_overwrites_a_status_changed_after_analysis(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.transactions.side_effect = [
        [], [SevdeskTransaction(55, 12, Decimal("50"), DATE, "mollie:tr_1 | PAYMENT", 200)]
    ]
    gateway.get_check_account_transaction_by_id.return_value = {"status": "400"}
    result = _service(tmp_path, gateway).reset_transactions_in_range(
        date(2026, 9, 1), date(2026, 9, 30)
    )
    assert result.success_count == 0
    assert result.failure_count == 1
    gateway.change_check_account_transaction_status.assert_not_called()


def test_cancelled_reset_performs_no_write(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.transactions.return_value = [
        SevdeskTransaction(55, 12, Decimal("50"), DATE, "mollie:tr_1 | PAYMENT", 200)
    ]
    result = _service(tmp_path, gateway).reset_transactions_in_range(
        date(2026, 9, 1), date(2026, 9, 30), cancelled=lambda: True
    )
    assert result.cancelled
    gateway.change_check_account_transaction_status.assert_not_called()


def test_invoice_paid_after_import_requires_review_instead_of_success(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.book_invoice.return_value = {"status": "invoice_already_paid"}
    repo = _MemoryRepo()
    service = _service(tmp_path, gateway, repo)

    first = service.book_selected([_row()])
    second = service.book_selected([_row()])

    assert first.failure_count == 1
    assert first.items[0].transaction_id == 99
    assert "zwischenzeitlich" in first.items[0].message
    assert second.failure_count == 1
    assert gateway.create_transaction.call_count == 1
    ledger = json.loads(repo.values["clearing.booking_ledger.v1"])
    key = f"{TransactionKind.PAYMENT.value}|mollie|tr_1"
    assert ledger["entries"][key]["state"] == "uncertain"


def test_conflicting_provider_reference_blocks_direct_order_fallback(tmp_path: Path) -> None:
    gateway = _gateway()
    provider = MagicMock()
    provider.last_warning = ""
    provider.fetch.return_value = [
        ProviderTransaction(
            "mollie", "tr_conflict", TransactionKind.PAYMENT, Decimal("50"), DATE,
            order_number="12345",
        )
    ]
    wix = MagicMock()
    wix.last_warning = ""
    wix.blocked_reference_ids = {"tr_conflict"}
    wix.provider_map.return_value = ({}, {})
    analysis = PaymentClearingService(
        mollie=provider, wix=wix, sevdesk=gateway, history_dir=tmp_path
    ).analyze(date(2026, 9, 1), date(2026, 9, 30))
    assert analysis.candidates[0].status == MatchStatus.MANUAL
    assert not analysis.candidates[0].selected


def test_incomplete_wix_lookup_blocks_unknown_reference_raw_fallback(tmp_path: Path) -> None:
    gateway = _gateway()
    provider = MagicMock()
    provider.last_warning = ""
    provider.fetch.return_value = [
        ProviderTransaction(
            "mollie", "tr_hidden", TransactionKind.PAYMENT, Decimal("50"), DATE,
            order_number="12345",
        )
    ]
    wix = MagicMock()
    wix.lookup_complete = False
    wix.last_warning = "Zahlungsabgleich unvollstaendig"
    wix.blocked_reference_ids = set()
    wix.provider_map.return_value = ({}, {})
    analysis = PaymentClearingService(
        mollie=provider, wix=wix, sevdesk=gateway, history_dir=tmp_path
    ).analyze(date(2026, 9, 1), date(2026, 9, 30))
    assert analysis.candidates[0].status == MatchStatus.MANUAL
    assert "unvollstaendig" in analysis.candidates[0].reason
    assert not analysis.candidates[0].selected


def test_analysis_stops_before_wix_after_last_provider_read(tmp_path: Path) -> None:
    gateway = _gateway()
    provider = MagicMock()
    provider.last_warning = ""
    provider.available.return_value = True
    cancelled = False

    def fetch(*_args: object) -> list[ProviderTransaction]:
        nonlocal cancelled
        cancelled = True
        return []

    provider.fetch.side_effect = fetch
    wix = MagicMock()
    service = PaymentClearingService(
        mollie=provider, wix=wix, sevdesk=gateway, history_dir=tmp_path
    )
    with pytest.raises(RuntimeError, match="abgebrochen"):
        service.analyze(
            date(2026, 9, 1), date(2026, 9, 30), cancelled=lambda: cancelled
        )
    wix.provider_map.assert_not_called()
    gateway.account_ids.assert_not_called()


def test_stop_preserves_completed_results_and_skips_remaining_rows(tmp_path: Path) -> None:
    gateway = _gateway()
    service = _service(tmp_path, gateway)
    stop = False

    def progress(value: int, text: str) -> None:
        nonlocal stop
        if value == 50:
            stop = True

    result = service.book_selected(
        [_row("po_1", TransactionKind.PAYOUT), _row("po_2", TransactionKind.PAYOUT)],
        progress=progress, cancelled=lambda: stop,
    )
    assert result.cancelled
    assert result.success_count == 1
    assert result.failure_count == 0
    assert result.cancelled_count == 1
    assert result.items[0].transaction_id == 99
    assert gateway.create_transaction.call_count == 1


def test_cancel_before_batch_performs_no_external_reads_or_writes(tmp_path: Path) -> None:
    gateway = _gateway()
    result = _service(tmp_path, gateway).book_selected([_row()], cancelled=lambda: True)
    assert result.cancelled_count == 1
    gateway.transactions.assert_not_called()
    gateway.create_transaction.assert_not_called()


def test_two_services_share_reservation_and_completed_checkpoint(tmp_path: Path) -> None:
    gateway = _gateway()
    repo = _MemoryRepo()
    first = _service(tmp_path, gateway, repo)
    second = _service(tmp_path, gateway, repo)
    row = _row("po_1", TransactionKind.PAYOUT)
    nested_results = []

    def create(**kwargs: object) -> int:
        nested_results.append(second.book_selected([row]))
        return 99

    gateway.create_transaction.side_effect = create
    assert first.book_selected([row]).success_count == 1
    assert nested_results[0].failure_count == 1
    assert gateway.create_transaction.call_count == 1
    again = second.book_selected([row])
    assert again.items[0].status == MatchStatus.ALREADY_BOOKED
    assert again.items[0].transaction_id == 99
    assert gateway.create_transaction.call_count == 1


def test_ambiguous_write_remains_blocked_after_restart(tmp_path: Path) -> None:
    gateway = _gateway()
    repo = _MemoryRepo()
    gateway.create_transaction.side_effect = TimeoutError("Unklarer POST-Ausgang")
    first = _service(tmp_path, gateway, repo).book_selected([_row()])
    assert first.failure_count == 1
    gateway.create_transaction.side_effect = None
    again = _service(tmp_path, gateway, repo).book_selected([_row()])
    assert again.failure_count == 1
    assert "unklar" in again.items[0].message
    assert gateway.create_transaction.call_count == 1


def test_prewrite_failure_releases_reservation(tmp_path: Path) -> None:
    gateway = _gateway()
    repo = _MemoryRepo()
    gateway.find_invoice.return_value = None
    assert _service(tmp_path, gateway, repo).book_selected([_row()]).failure_count == 1
    gateway.find_invoice.return_value = InvoiceRecord(7, "RE-1", "12345", Decimal("50"), 200, "Test")
    assert _service(tmp_path, gateway, repo).book_selected([_row()]).success_count == 1


def test_same_invoice_cannot_be_reserved_for_two_payments() -> None:
    repo = _MemoryRepo()
    store = ClearingBookingStore(repo)  # type: ignore[arg-type]
    store.claim(_row("tr_1"))
    with pytest.raises(RuntimeError, match="Rechnung.*reserviert"):
        store.claim(_row("tr_2"))


def test_central_and_local_history_failure_are_visible(tmp_path: Path) -> None:
    gateway = _gateway()
    repo = MagicMock()
    repo.set_value_json.side_effect = RuntimeError("DB down")
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file", encoding="utf-8")
    service = PaymentClearingService(sevdesk=gateway, history_dir=blocked)
    service._repo = repo
    result = service.book_selected([_row("po_1", TransactionKind.PAYOUT)])
    assert result.success_count == 1
    assert len(result.warnings) == 2


def test_sepa_range_and_ambiguous_purpose_do_not_auto_book(tmp_path: Path) -> None:
    gateway = _gateway()
    gateway.transactions.side_effect = lambda account_id, start, end: [
        SevdeskTransaction(1, 12, Decimal("50"), datetime(2026, 8, 10, tzinfo=TZ), "Wix 12345", 100),
        SevdeskTransaction(2, 12, Decimal("50"), DATE, "Bestellungen 12345 und 67890", 100),
    ] if account_id == 12 else []
    result = _service(tmp_path, gateway).analyze(date(2026, 9, 1), date(2026, 9, 30))
    assert not any(row.selected for row in result.candidates)
    assert not any(row.payment_date.month == 8 for row in result.candidates)
    assert result.candidates[0].reason == "Mehrere moegliche Bestellnummern im Zahlungszweck"


def test_delayed_standalone_mollie_payment_loads_older_wix_refs(tmp_path: Path) -> None:
    gateway = _gateway()
    mollie = MagicMock()
    mollie.last_warning = ""
    mollie.fetch.return_value = [
        ProviderTransaction("mollie", "tr_old", TransactionKind.PAYMENT, Decimal("50"), DATE)
    ]
    wix = MagicMock()
    wix.last_warning = ""
    wix.provider_map.side_effect = [({}, {}), ({"tr_old": "12345"}, {})]
    service = PaymentClearingService(
        mollie=mollie, wix=wix, sevdesk=gateway, history_dir=tmp_path
    )
    analysis = service.analyze(date(2026, 9, 1), date(2026, 9, 30))
    assert analysis.candidates[0].status == MatchStatus.READY
    assert wix.provider_map.call_count == 2
    assert wix.provider_map.call_args_list[1].args[0].date() == date(2026, 6, 3)


def test_failed_invoice_book_checkpoint_preserves_import_id(tmp_path: Path) -> None:
    gateway = _gateway()
    repo = _MemoryRepo()
    gateway.book_invoice.return_value = {"status": "not_booked"}
    result = _service(tmp_path, gateway, repo).book_selected([_row()])
    assert result.failure_count == 1
    assert result.items[0].transaction_id == 99
    ledger = json.loads(repo.values["clearing.booking_ledger.v1"])
    entry = ledger["entries"]["payment|mollie|tr_1"]
    assert entry["transaction_id"] == 99
    assert entry["state"] == "uncertain"
