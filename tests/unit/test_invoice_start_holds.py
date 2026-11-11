"""Persistent START holds gate drafts and the finalized-invoice recovery path."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from types import MethodType

import pytest

from xw_office.services.invoice_processing.service import FulfillmentFlags, InvoiceProcessingService
from xw_office.services.invoice_processing.start_holds import START_HOLDS_KEY, StartHold
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def mutate_value_json(self, key: str, mutator: object) -> str:
        updated = mutator(self.values.get(key))
        self.values[key] = updated
        return updated


def _service() -> tuple[InvoiceProcessingService, _Settings]:
    service = object.__new__(InvoiceProcessingService)
    settings = _Settings()
    service._settings_repo = settings  # noqa: SLF001
    return service, settings


def test_start_hold_is_persistent_and_release_restores_draft() -> None:
    service, settings = _service()
    hold = service.defer_invoice_from_start(
        "42", "customer_question", note="Artikel noch klären", review_on="2026-11-20"
    )
    assert hold.reason_label == "Kundenklärung"
    assert json.loads(settings.values[START_HOLDS_KEY])["42"]["review_on"] == "2026-11-20"
    assert service.filter_start_ready([InvoiceSummary(id="42"), InvoiceSummary(id="43")]) == [
        InvoiceSummary(id="43")
    ]
    service.release_invoice_for_start("42")
    assert service.get_start_hold("42") is None


def test_stale_pc_cannot_overwrite_or_release_a_changed_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _settings = _service()
    old = service.defer_invoice_from_start("42", "customer_question")
    with pytest.raises(RuntimeError, match="inzwischen"):
        service.defer_invoice_from_start("42", "other", expected_ready=True)
    create_hold = StartHold.create

    def same_timestamp(
        cls: type[StartHold], invoice_id: str, reason: str, *, note: str = "", review_on: str = ""
    ) -> StartHold:
        return replace(
            create_hold(invoice_id, reason, note=note, review_on=review_on),
            updated_at=old.updated_at,
        )

    monkeypatch.setattr(StartHold, "create", classmethod(same_timestamp))
    updated = service.defer_invoice_from_start("42", "product_unavailable")
    assert datetime.fromisoformat(updated.updated_at) > datetime.fromisoformat(old.updated_at)
    with pytest.raises(RuntimeError, match="anderen PC"):
        service.release_invoice_for_start("42", expected_updated_at=old.updated_at)
    assert service.get_start_hold("42").reason == "product_unavailable"


def test_invalid_hold_store_stops_start_instead_of_releasing_holds() -> None:
    service, settings = _service()
    settings.values[START_HOLDS_KEY] = "{broken"
    with pytest.raises(RuntimeError, match="nicht lesbar"):
        service.list_start_holds()


def test_invoice_row_shows_unchecked_hold_with_reason_and_reminder() -> None:
    service, _settings = _service()
    service.defer_invoice_from_start(
        "42", "customer_question", note="Antwort offen", review_on="2026-01-01"
    )
    service._load_fulfillment_flags_map = MethodType(lambda _self: {}, service)  # type: ignore[method-assign]  # noqa: SLF001
    rows = service._rows_with_fulfillment([InvoiceSummary(id="42", status=100)])  # noqa: SLF001
    assert rows[0]["__start_selectable__"] is True
    assert rows[0]["__start_checked__"] is False
    assert rows[0]["__start_due__"] is True
    assert "Kundenklärung" in rows[0]["__tooltip__START"]


def test_new_draft_is_checked_for_start_by_default() -> None:
    service, _settings = _service()
    service._load_fulfillment_flags_map = MethodType(lambda _self: {}, service)  # type: ignore[method-assign]  # noqa: SLF001
    rows = service._rows_with_fulfillment([InvoiceSummary(id="43", status=100)])  # noqa: SLF001
    assert rows[0]["__start_selectable__"] is True
    assert rows[0]["__start_checked__"] is True


def test_full_start_only_receives_ready_drafts() -> None:
    service, _settings = _service()
    service.defer_invoice_from_start("42", "product_unavailable")
    service._customer_aftercare = None  # noqa: SLF001
    captured: list[str] = []
    service._load_start_target_summaries = MethodType(  # type: ignore[method-assign]  # noqa: SLF001
        lambda _self, **_kwargs: [InvoiceSummary(id="42"), InvoiceSummary(id="43")], service
    )
    service._resume_incomplete_fulfillment = MethodType(  # type: ignore[method-assign]  # noqa: SLF001
        lambda _self, **_kwargs: {"processed": 0, "failures": 0, "successful": 0, "aborted": False}, service
    )
    service._prefetch_wix_order_context = MethodType(lambda _self, _summaries: None, service)  # type: ignore[method-assign]  # noqa: SLF001
    service._start_delivery_kind = MethodType(lambda _self, _summary: "physical", service)  # type: ignore[method-assign]  # noqa: SLF001
    service._start_processing_priority = MethodType(lambda _self, _summary, **_kwargs: (0,), service)  # type: ignore[method-assign]  # noqa: SLF001

    def fake_run(_self: object, **kwargs: object) -> dict[str, object]:
        captured.extend(summary.id for summary in kwargs["summaries"])
        return {"processed": 1, "failures": 0, "successful": 1, "aborted": False}

    service._run_start_fullflow_print_first = MethodType(fake_run, service)  # type: ignore[method-assign]  # noqa: SLF001
    service.run_start_fullflow(full_mode=True)
    assert captured == ["43"]


def test_finalized_recovery_does_not_resume_held_invoice() -> None:
    service, _settings = _service()
    service.defer_invoice_from_start("42", "customer_question")
    service._load_fulfillment_flags_map = MethodType(  # type: ignore[method-assign]  # noqa: SLF001
        lambda _self: {"42": FulfillmentFlags(last_run_iso=datetime.now(timezone.utc).isoformat())},
        service,
    )
    result = service._resume_incomplete_fulfillment(  # noqa: SLF001
        should_abort=None, progress_callback=None, mail_recipient_override=None
    )
    assert result["processed"] == 0
