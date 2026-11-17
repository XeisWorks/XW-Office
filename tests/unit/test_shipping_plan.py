from datetime import date
import json

import pytest

from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.invoice_processing.shipping_plan import (
    abroad_with_at_default, candidate_from_summary, compact_customer_name, pending_abroad,
)
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def test_physical_lanes_keep_plc_with_austria_and_exclude_digital() -> None:
    summary = InvoiceSummary(id="1", delivery_country_code="DE", contact_name="Test")
    plc = candidate_from_summary(summary, wix_country="Germany", plc=True)
    assert plc.lane == "at"
    assert plc.plc
    assert candidate_from_summary(summary, wix_country="Deutschland").lane == "abroad"
    assert candidate_from_summary(summary, digital_only=True, plc=True).lane == "digital"


def test_compact_buyer_names_keep_company_only() -> None:
    assert compact_customer_name("Muster GmbH | Anna Muster") == "Muster GmbH"
    assert compact_customer_name("Muster GmbH / Anna Muster") == "Muster GmbH"
    assert compact_customer_name("Anna Muster") == "Anna Muster"
    summary = InvoiceSummary(id="7", contact_name="Anna Muster")
    candidate = candidate_from_summary(
        summary, wix_name="Muster GmbH / Anna Muster", wix_company="Muster GmbH",
    )
    assert candidate.customer_name == "Muster GmbH"
    summary_with_company = InvoiceSummary(id="8", contact_name="Muster GmbH | Anna Muster")
    assert candidate_from_summary(
        summary_with_company, wix_name="Anna Muster",
    ).customer_name == "Muster GmbH"


def test_abroad_batch_counts_pending_eu_but_not_digital_or_non_eu() -> None:
    eu = candidate_from_summary(InvoiceSummary(id="1"), wix_country="CH")
    non_eu = candidate_from_summary(InvoiceSummary(id="2"), wix_country="US")
    digital = candidate_from_summary(InvoiceSummary(id="3"), wix_country="DE", digital_only=True)
    records = {
        "old-eu": {"lane": "abroad", "eu_ch": "1", "planned_date": "2026-11-19", "shipped_date": ""},
        "sent-eu": {"lane": "abroad", "eu_ch": "1", "planned_date": "2026-11-18", "shipped_date": "2026-11-18"},
    }
    pending = pending_abroad(records)
    assert len(pending) == 1
    assert not abroad_with_at_default([eu, non_eu, digital], pending)
    assert abroad_with_at_default([eu, eu, non_eu, digital], pending)


class _Settings:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self.values.get(key)

    def mutate_value_json(self, key: str, callback: object) -> None:
        self.values[key] = callback(self.values.get(key))


def test_shipping_ledger_merges_planned_and_actual_dates() -> None:
    service = InvoiceProcessingService.__new__(InvoiceProcessingService)
    service._settings_repo = _Settings()  # type: ignore[attr-defined]
    service.update_shipping_dates({"123": {
        "invoice_date": "2026-11-17", "lane": "abroad", "planned_date": "2026-11-20",
    }})
    service.update_shipping_dates({"123": {"shipped_date": "2026-11-21"}})
    service.update_shipping_dates({"456": {"planned_date": "2026-11-22"}})
    service.update_shipping_dates({"789": {
        "lane": "abroad", "planned_date": "2026-11-22", "at_planned_date": "2026-11-18",
    }})
    service.mark_plc_shipping_lane("789")
    records = service.read_shipping_dates()
    assert records["123"] == {
        "invoice_date": "2026-11-17", "lane": "abroad",
        "planned_date": "2026-11-20", "shipped_date": "2026-11-21",
    }
    assert records["456"]["planned_date"] == "2026-11-22"
    assert records["789"]["lane"] == "at"
    assert records["789"]["planned_date"] == "2026-11-18"
    with pytest.raises(ValueError):
        service.update_shipping_dates({"123": {"shipped_date": "not-a-date"}})
    assert json.loads(next(iter(service._settings_repo.values.values())))["123"]["shipped_date"] == "2026-11-21"


def test_shipping_date_dialog_one_click_and_separate_calendar(qtbot: object) -> None:
    from xw_office.ui.modules.rechnungen.shipping_date_dialog import ShippingDateDialog

    eu = candidate_from_summary(InvoiceSummary(id="1"), wix_country="DE")
    at = candidate_from_summary(InvoiceSummary(id="2"), wix_country="AT")
    dialog = ShippingDateDialog(today=date(2026, 11, 17))
    qtbot.addWidget(dialog)
    chosen: list[tuple[str, str]] = []
    dialog.dates_chosen.connect(lambda at_day, abroad_day: chosen.append((at_day, abroad_day)))
    dialog.set_shipments([at, eu, eu, eu], [])
    assert dialog._together.isChecked()
    assert dialog._at_buttons[0].text().startswith("Di")
    dialog._at_buttons[0].click()
    assert chosen == [("2026-11-17", "2026-11-17")]

    separate = ShippingDateDialog(today=date(2026, 11, 17))
    qtbot.addWidget(separate)
    chosen.clear()
    separate.dates_chosen.connect(lambda at_day, abroad_day: chosen.append((at_day, abroad_day)))
    separate.set_shipments([at, eu], [])
    assert not separate._together.isChecked()
    separate._at_buttons[1].click()
    assert chosen == []
    separate._abroad_buttons[3].click()
    assert chosen == [("2026-11-18", "2026-11-20")]
