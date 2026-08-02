"""Tests for XW-Copilot live action dispatcher."""
from __future__ import annotations

from xw_office.services.xw_copilot.live_dispatch import XWCopilotLiveDispatcher


# ---------------------------------------------------------------------------
# Stub service implementations
# ---------------------------------------------------------------------------

class _FakeCrm:
    def has_live_connection(self) -> bool:
        return True

    def fetch_live_contacts(self):  # type: ignore[return]
        from xw_office.services.crm.types import ContactRecord
        return [
            ContactRecord(id="1", name="Max Mustermann", email="max@test.at"),
            ContactRecord(id="2", name="Erika Muster", email="erika@test.at"),
        ]


class _FakeInvoiceProcessing:
    def load_invoice_summaries(self, *, limit: int = 50, offset: int = 0, status=None):  # type: ignore[return]
        from xw_office.services.sevdesk.invoice_client import InvoiceSummary
        return [
            InvoiceSummary(id="inv1", invoiceNumber="XW-001"),
            InvoiceSummary(id="inv2", invoiceNumber="XW-002"),
        ]


class _FakeInventory:
    def build_start_preflight(self, open_invoice_count: int):  # type: ignore[return]
        from xw_office.services.inventory.service import StartDecision, StartPreflight
        return StartPreflight(
            open_invoice_count=open_invoice_count,
            decisions=[
                StartDecision(
                    sku="XW-4001",
                    required_qty=3,
                    on_hand_qty=1,
                    missing_qty=2,
                    final_print_qty=5,
                    will_print=True,
                )
            ],
            missing_position_data=False,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_crm_lookup_returns_matches() -> None:
    dispatcher = XWCopilotLiveDispatcher(crm_service=_FakeCrm())  # type: ignore[arg-type]
    result = dispatcher.dispatch("crm.lookup_contact", {"query": "muster"})

    assert result is not None
    assert result["service"] == "crm"
    contacts = result["contacts"]
    assert len(contacts) == 2
    assert contacts[0]["name"] == "Max Mustermann"


def test_crm_lookup_filters_by_query() -> None:
    dispatcher = XWCopilotLiveDispatcher(crm_service=_FakeCrm())  # type: ignore[arg-type]
    result = dispatcher.dispatch("crm.lookup_contact", {"query": "max"})

    assert result is not None
    assert len(result["contacts"]) == 1
    assert result["contacts"][0]["name"] == "Max Mustermann"


def test_invoice_read_returns_all_when_no_filter() -> None:
    dispatcher = XWCopilotLiveDispatcher(invoice_processing=_FakeInvoiceProcessing())  # type: ignore[arg-type]
    result = dispatcher.dispatch("invoice.read_status", {"invoice_number": ""})

    assert result is not None
    assert len(result["invoices"]) == 2


def test_invoice_read_filters_by_number() -> None:
    dispatcher = XWCopilotLiveDispatcher(invoice_processing=_FakeInvoiceProcessing())  # type: ignore[arg-type]
    result = dispatcher.dispatch("invoice.read_status", {"invoice_number": "XW-001"})

    assert result is not None
    assert len(result["invoices"]) == 1
    assert result["invoices"][0]["number"] == "XW-001"


def test_inventory_preflight_returns_decisions() -> None:
    dispatcher = XWCopilotLiveDispatcher(inventory_service=_FakeInventory())  # type: ignore[arg-type]
    result = dispatcher.dispatch("inventory.start_preflight", {"sku": "", "quantity": 1})

    assert result is not None
    assert len(result["decisions"]) == 1
    assert result["decisions"][0]["sku"] == "XW-4001"
    assert result["decisions"][0]["will_print"] is True


def test_unsupported_action_returns_none() -> None:
    dispatcher = XWCopilotLiveDispatcher()
    result = dispatcher.dispatch("unknown.action", {})
    assert result is None


def test_missing_crm_service_returns_error() -> None:
    dispatcher = XWCopilotLiveDispatcher(crm_service=None)
    result = dispatcher.dispatch("crm.lookup_contact", {"query": "test"})
    assert result is not None
    assert "error" in result


def test_live_mode_used_in_dry_run_service() -> None:
    """When mode is live and live dispatcher is available, it takes priority."""
    from xw_office.services.xw_copilot.dry_run import XWCopilotDryRunService
    from xw_office.services.xw_copilot.service import XWCopilotConfig

    class _CfgStub:
        def load_config(self) -> XWCopilotConfig:
            return XWCopilotConfig(enabled=True, mode="live")

    dispatcher = XWCopilotLiveDispatcher(crm_service=_FakeCrm())  # type: ignore[arg-type]
    svc = XWCopilotDryRunService(
        _CfgStub(),  # type: ignore[arg-type]
        live_dispatcher=dispatcher,
    )

    response = svc.simulate_raw_request(
        '{"tenant":"x","mailbox":"y","action":"crm.lookup_contact",'
        '"payload_version":"1.0","payload":{"query":"Mustermann"}}'
    )

    assert response.accepted is True
    assert response.mode == "live"
    # Live result contains real contacts list, not dry_run_note
    assert "dry_run_note" not in response.preview
    assert "contacts" in response.preview
