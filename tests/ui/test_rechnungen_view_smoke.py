"""Smoke tests for the Rechnungen daily-business view."""
from __future__ import annotations

import subprocess
from threading import Event
import types

from PySide6.QtWidgets import QToolButton

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.draft_invoice.service import DraftInvoiceService
from xw_studio.services.inventory.service import StartMode, StartPreflight
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.products.print_decision import PieceBlock, PrintDecisionEngine
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.transfers.service import OffeneUeberweisungenService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.ui.main_window import MainWindow
from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView, _StartDialog
from xw_studio.ui.modules.rechnungen.plc_label_dialog import PlcLabelPrintDialog
from xw_studio.ui.modules.rechnungen.view import (
    RechnungenView,
    _ActionsDelegate,
    _DraftInvoiceDialog,
)


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def _wait_embedded_rechnungen(qtbot: object, view: TagesgeschaeftView) -> RechnungenView:
    qtbot.waitUntil(lambda: view._rechnungen_view is not None, timeout=3000)  # type: ignore[attr-defined]  # noqa: SLF001
    assert view._rechnungen_view is not None  # noqa: SLF001
    return view._rechnungen_view  # noqa: SLF001


def test_draft_preview_is_non_blocking(qtbot: object) -> None:
    container = _build_container()
    entered = Event()
    release = Event()

    class _DraftService:
        def preview_wix_order_number(self, reference: str) -> dict[str, object]:
            entered.set()
            release.wait(timeout=2)
            return {
                "wix_order_number": reference,
                "customer": "Testkunde",
                "email": "test@example.invalid",
                "items": [],
                "can_create": True,
            }

    container.register(DraftInvoiceService, lambda _c: _DraftService())  # type: ignore[arg-type,return-value]
    view = RechnungenView(container)
    dialog = _DraftInvoiceDialog(view)
    qtbot.addWidget(view)
    qtbot.addWidget(dialog)
    dialog._order_number.setText("20519")  # noqa: SLF001

    view._run_draft_preview(dialog)  # noqa: SLF001

    assert entered.wait(timeout=1)
    assert not dialog._btn_preview.isEnabled()  # noqa: SLF001
    assert "geladen" in dialog._btn_preview.text()  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: dialog.preview_ok, timeout=2000)
    assert dialog._btn_preview.isEnabled()  # noqa: SLF001


class _FakeSecretService:
    def get_secret(self, key: str) -> str:
        if key in {"SEVDESK_API_TOKEN", "WIX_API_KEY", "WIX_SITE_ID"}:
            return "test-token"
        if key == "OUTLOOK_SENDER_EMAIL":
            return "office@xeisworks.at"
        return ""


class _FakeHint:
    def as_row_patch(self) -> dict[str, object]:
        return {
            "Hinweise": "",
            "__icons__Hinweise": [],
            "__tooltip__Hinweise": "",
            "__fg__Hinweise": "",
        }


class _FakeInvoiceProcessingService:
    def __init__(self) -> None:
        self.load_calls: list[tuple[str, int, int]] = []
        self._draft = InvoiceSummary.model_validate(
            {
                "id": "draft-1",
                "invoiceNumber": "RE-DRAFT",
                "invoiceDate": "2026-06-19T00:00:00",
                "status": 100,
                "sumGross": "10.0",
                "contact_name": "Draft Customer",
                "order_reference": "20844",
            }
        )
        self._open = InvoiceSummary.model_validate(
            {
                "id": "open-1",
                "invoiceNumber": "RE-OPEN",
                "invoiceDate": "2026-06-19T00:00:00",
                "status": 1000,
                "sumGross": "20.0",
                "contact_name": "Open Customer",
                "order_reference": "20845",
            }
        )

    def load_invoice_batch(
        self,
        *,
        status: int,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary]]:
        self.load_calls.append((f"status:{status}", limit, offset))
        summaries = [self._draft] if status == 100 else [self._open]
        if offset:
            summaries = []
        return [summary.as_table_row() for summary in summaries], summaries

    def load_recent_non_draft_batch(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, str]], list[InvoiceSummary]]:
        self.load_calls.append(("recent", limit, offset))
        summaries = [self._open]
        if offset:
            summaries = []
        return [summary.as_table_row() for summary in summaries], summaries

    def count_invoices(self, status: int) -> int:
        return 1 if status == 100 else 0

    def get_cached_invoice_list_hints(self, _reference: str) -> None:
        return None

    def resolve_invoice_list_hints(self, _reference: str) -> _FakeHint:
        return _FakeHint()

    def get_cached_invoice_detail_context(self, _summary: InvoiceSummary) -> dict[str, object]:
        return {}

    def get_invoice_detail_context(self, _summary: InvoiceSummary) -> dict[str, object]:
        return {}

    def is_flagged_sku(self, _sku: str) -> bool:
        return False


class _FakeWixOrdersClient:
    def has_credentials(self) -> bool:
        return True

    def resolve_order_summary(self, reference: str) -> dict[str, str]:
        return {
            "wix_order_number": reference,
            "wix_customer_name": f"Customer {reference}",
            "wix_customer_email": f"customer-{reference}@example.test",
            "wix_shipping_country": "Austria",
            "wix_shipping_address": (
                f"Customer {reference}\n"
                "Teststrasse 1\n"
                "1010 Wien\n"
                "AUSTRIA"
            ),
        }

    def fetch_order_line_items(self, _reference: str) -> list[dict[str, object]]:
        return []

    def get_cached_order_summary(self, _reference: str) -> dict[str, str] | None:
        return None

    def get_cached_order_line_items(self, _reference: str) -> list[object] | None:
        return None

    def is_reference_digital_only(self, _reference: str) -> bool:
        return False


class _FakePrintDecisionEngine:
    def get_piece_blocks(
        self,
        _items: list[dict[str, object]],
        *,
        invoice_ref: str | None = None,
    ) -> list[object]:
        return []


class _FakeDailyBusinessService:
    def load_counts(self, open_invoice_count: int = 0) -> dict[str, int]:
        return {
            "rechnungen": open_invoice_count,
            "mollie": 0,
            "gutscheine": 0,
        }


class _FakeOffeneSendungenService:
    def open_count(self) -> int:
        return 0

    def refresh_count_from_graph_silent(self, *, lookback_days: int = 20, max_items: int = 120) -> int:
        return self.open_count()


class _FakeOffeneUeberweisungenService:
    def __init__(self, count: int = 0, login_required: bool = False) -> None:
        self._count = count
        self._login_required = login_required

    def open_count(self) -> int:
        return self._count

    def refresh_count_from_graph_silent(self, *, lookback_days: int = 60, max_items: int = 150) -> int:
        del lookback_days, max_items
        return self._count

    def needs_interactive_graph_login(self) -> bool:
        return self._login_required


def _build_rechnungen_test_container() -> tuple[Container, _FakeInvoiceProcessingService]:
    container = _build_container()
    invoice_service = _FakeInvoiceProcessingService()
    container.register(SecretService, lambda _: _FakeSecretService())
    container.register(InvoiceProcessingService, lambda _: invoice_service)
    container.register(WixOrdersClient, lambda _: _FakeWixOrdersClient())
    container.register(PrintDecisionEngine, lambda _: _FakePrintDecisionEngine())
    container.register(DailyBusinessService, lambda _: _FakeDailyBusinessService())
    container.register(OffeneSendungenService, lambda _: _FakeOffeneSendungenService())
    container.register(OffeneUeberweisungenService, lambda _: _FakeOffeneUeberweisungenService())
    return container, invoice_service


def test_rechnungen_shutdown_suppresses_wix_warmup_restart(qtbot: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._wix_warm_queue = ["20844"]  # noqa: SLF001

    assert view.prepare_shutdown() is True
    view._warm_wix_context_for_summaries([invoice_service._draft])  # noqa: SLF001
    view._on_wix_warm_finished()  # noqa: SLF001

    assert view._wix_warm_queue == []  # noqa: SLF001
    assert view._wix_warm_worker is None  # noqa: SLF001
    assert view._wix_warm_handle is None  # noqa: SLF001


def test_tagesgeschaeft_contains_rechnungen_view(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)
    assert hasattr(view, "_rechnungen_view")  # noqa: SLF001
    assert view._btn_start.text() == "▶ START"  # noqa: SLF001
    assert view._btn_start.menu() is not None  # noqa: SLF001
    assert [action.text() for action in view._btn_start.menu().actions()] == [  # noqa: SLF001
        "Selected",
        "+ Noten",
        "+ Noten Selected",
    ]
    assert view._btn_refresh.text() == "Aktualisieren"  # noqa: SLF001
    assert view._btn_draft.text() == "Entwurf"  # noqa: SLF001
    assert view._btn_custom_label.text() == "Custom-Label"  # noqa: SLF001
    assert view._btn_stop.text() == "STOP"  # noqa: SLF001
    assert not view._btn_stop.isEnabled()  # noqa: SLF001
    assert not view._rechnungen_view._toolbar.isVisible()  # noqa: SLF001
    bar_layout = view._btn_start.parentWidget().layout()  # noqa: SLF001
    widgets = [bar_layout.itemAt(i).widget() for i in range(bar_layout.count())]
    assert widgets.index(view._btn_start) == widgets.index(view._btn_stop) - 1  # noqa: SLF001
    assert widgets.index(view._btn_stop) == widgets.index(view._btn_beenden) - 1  # noqa: SLF001


def test_start_click_disables_start_immediately(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)
    started = {"value": False}

    def fake_start(self) -> None:
        started["value"] = True

    monkeypatch.setattr(
        "xw_studio.ui.modules.rechnungen.tagesgeschaeft_view.BackgroundWorker.start",
        fake_start,
    )

    view._on_start_clicked()  # noqa: SLF001

    assert started["value"] is True
    assert not view._btn_start.isEnabled()  # noqa: SLF001
    assert view._btn_start.text() == "START..."  # noqa: SLF001
    assert view._btn_stop.isEnabled()  # noqa: SLF001
    assert "START wird vorbereitet." in view._rechnungen_view._start_summary_label.text()  # noqa: SLF001


def test_tagesgeschaeft_alert_buttons_follow_counts(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._update_alert_button(view._btn_sendungen_alert, "OFFENE SENDUNGEN", 0)  # noqa: SLF001
    assert view._btn_sendungen_alert.isHidden()  # noqa: SLF001

    view._update_alert_button(view._btn_sendungen_alert, "OFFENE SENDUNGEN", 2)  # noqa: SLF001

    assert view._btn_sendungen_alert.text() == "OFFENE SENDUNGEN (2)"  # noqa: SLF001
    assert not view._btn_sendungen_alert.isHidden()  # noqa: SLF001


def test_tagesgeschaeft_transfer_button_label_and_spacing(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    assert view._btn_transfer_alert.text() == "UEBERWEISUNG OFFEN"  # noqa: SLF001

    bar_layout = view._btn_start.parentWidget().layout()  # noqa: SLF001
    start_idx = -1
    for idx in range(bar_layout.count()):
        item = bar_layout.itemAt(idx)
        if item.widget() is view._btn_start:
            start_idx = idx
            break
    assert start_idx > 0
    spacer_before_start = bar_layout.itemAt(start_idx - 1)
    assert spacer_before_start.widget() is None
    assert spacer_before_start.spacerItem() is not None


def test_transfer_alert_click_updates_badge_from_dialog_result(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)

    monkeypatch.setattr(view._rechnungen_view, "open_ueberweisungen_dialog", lambda: 3)  # noqa: SLF001

    view._on_transfer_alert_clicked()  # noqa: SLF001

    assert view._btn_transfer_alert.text() == "UEBERWEISUNG OFFEN (3)"  # noqa: SLF001
    assert not view._btn_transfer_alert.isHidden()  # noqa: SLF001


def test_transfer_alert_shows_login_when_graph_auth_required(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._on_badges_result(  # noqa: SLF001
        {
            "rechnungen": 0,
            "mollie": 0,
            "gutscheine": 0,
            "sendungen": 0,
            "transfer": 0,
            "transfer_login_required": 1,
        }
    )

    assert view._btn_transfer_alert.text() == "UEBERWEISUNG LOGIN"  # noqa: SLF001
    assert not view._btn_transfer_alert.isHidden()  # noqa: SLF001


def test_actions_delegate_exposes_mail_action() -> None:
    layout = _ActionsDelegate._layout(width=120, height=28)  # noqa: SLF001
    assert [key for key, _x, _size in layout] == ["post", "wix", "mail"]
    mail_key, mail_x, mail_size = layout[-1]
    assert _ActionsDelegate.action_at_x(mail_x + mail_size / 2, width=120, height=28) == mail_key


def test_customer_mail_action_opens_mailto_url(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    opened: list[str] = []

    def fake_open_url(url: object) -> bool:
        opened.append(bytes(url.toEncoded()).decode("utf-8"))  # type: ignore[attr-defined]
        return True

    monkeypatch.setattr(
        "xw_studio.ui.modules.rechnungen.view.QDesktopServices.openUrl",
        fake_open_url,
    )

    summary = invoice_service._draft  # noqa: SLF001
    view._open_customer_mail_url("customer-20844@example.test", view._customer_mail_subject(summary))  # noqa: SLF001

    assert opened
    assert opened[0].startswith("mailto:customer-20844@example.test?")
    assert "subject=Best.-Nr.%2020844%20%7C%20RE-DRAFT" in opened[0]


def test_customer_mail_row_action_dispatches(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    called: list[str] = []

    def fake_open_customer_mail(summary: InvoiceSummary) -> None:
        called.append(summary.id)

    monkeypatch.setattr(view, "_open_customer_mail", fake_open_customer_mail)

    view._run_row_action(invoice_service._draft, "mail")  # noqa: SLF001

    assert called == ["draft-1"]


def test_customer_mail_outlook_runs_in_subprocess(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    calls: list[dict[str, object]] = []

    def fake_run(*args: object, **kwargs: object) -> object:
        calls.append({"args": args[0], **dict(kwargs)})
        return types.SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    summary = invoice_service._draft  # noqa: SLF001
    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.view.subprocess.run", fake_run)

    assert view._open_customer_mail_outlook("kunde@example.test", view._customer_mail_subject(summary)) is True  # noqa: SLF001
    assert calls
    assert calls[0]["timeout"] == 20
    assert "outlook_compose" in " ".join(calls[0]["args"])  # type: ignore[arg-type]
    assert "kunde@example.test" in str(calls[0]["input"])
    assert "office@xeisworks.at" in str(calls[0]["input"])


def test_customer_mail_outlook_timeout_falls_back(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    def fake_run(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="outlook", timeout=20)

    summary = invoice_service._draft  # noqa: SLF001
    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.view.subprocess.run", fake_run)

    assert view._open_customer_mail_outlook("kunde@example.test", view._customer_mail_subject(summary)) is False  # noqa: SLF001


def test_start_dialog_keeps_full_mode_when_print_plan_missing(qtbot: object) -> None:
    preflight = StartPreflight(open_invoice_count=2, decisions=[], missing_position_data=True)
    dialog = _StartDialog(preflight, initial_mode=StartMode.INVOICES_AND_PRINT)
    qtbot.addWidget(dialog)

    assert dialog.full_mode is True
    assert dialog.selected_mode == StartMode.INVOICES_AND_PRINT
    assert dialog._mode_full.isEnabled()  # noqa: SLF001


def test_plain_start_skips_inventory_dialog(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    preflight = StartPreflight(open_invoice_count=2, decisions=[], missing_position_data=True)
    called = {"product_check": 0, "dialog": 0}

    def fake_product_check() -> None:
        called["product_check"] += 1

    def fake_exec(self) -> int:
        called["dialog"] += 1
        return 0

    monkeypatch.setattr(view, "_start_missing_product_check", fake_product_check)
    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.tagesgeschaeft_view._StartDialog.exec", fake_exec)

    view._start_include_product_print = False  # noqa: SLF001
    view._on_start_preflight_ready(preflight)  # noqa: SLF001

    assert called == {"product_check": 1, "dialog": 0}


def test_rechnungen_toolbar_controls_exist(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    assert view._btn_more.text() == "Weitere Rechnungen laden"  # noqa: SLF001
    assert view._btn_draft.text() == "Rechnungs-Entwurf"  # noqa: SLF001
    assert view._btn_custom_label.text() == "CUSTOM-LABEL"  # noqa: SLF001
    assert view._btn_print.text() == "Rechnung drucken"  # noqa: SLF001
    assert view._btn_print_label.toolTip() == "Label drucken"  # noqa: SLF001
    assert view._btn_print_plc.text() == "PLC-Label drucken"  # noqa: SLF001
    assert view._btn_print_music.text() == "Noten drucken"  # noqa: SLF001
    assert view._btn_send_invoice.text() == "Rechnung senden"  # noqa: SLF001
    assert view._shipping_editor is not None  # noqa: SLF001
    assert view._gb_actions.isHidden()  # noqa: SLF001
    assert not view._btn_print.isEnabled()  # noqa: SLF001
    assert not view._btn_print_label.isEnabled()  # noqa: SLF001
    assert not view._btn_print_plc.isEnabled()  # noqa: SLF001
    assert not view._btn_print_music.isEnabled()  # noqa: SLF001
    assert not view._btn_send_invoice.isEnabled()  # noqa: SLF001


def test_rechnungen_selection_sets_summary_before_cache_hydration(qtbot: object, monkeypatch) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "quick-select-1",
            "invoiceNumber": "RE-QUICK",
            "status": 200,
            "contact_name": "Sofort Kunde",
            "order_reference": "20901",
        }
    )
    hydrate_calls: list[str] = []

    def fake_hydrate(next_summary: InvoiceSummary, _seq: int) -> None:
        hydrate_calls.append(str(next_summary.id))

    monkeypatch.setattr(view, "_hydrate_detail_for_selection", fake_hydrate)

    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001

    assert view._dl_number.text() == "RE-QUICK"  # noqa: SLF001
    assert view._dl_contact.text() == "Sofort Kunde"  # noqa: SLF001
    assert hydrate_calls == []
    qtbot.waitUntil(lambda: hydrate_calls == ["quick-select-1"], timeout=1000)


def test_rechnungen_open_overview_resolves_wix_classification_and_buyer_notes(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()

    class _OverviewInvoiceService(_FakeInvoiceProcessingService):
        def resolve_invoice_list_hints(self, reference: str) -> object:
            note = "Bitte PLC Versandlabel pruefen" if reference == "20910" else "Download-Link bitte senden"
            return types.SimpleNamespace(buyer_note=note)

        def is_flagged_sku(self, sku: str) -> bool:
            return sku == "XW-PHYS"

    class _OverviewWixClient(_FakeWixOrdersClient):
        def is_reference_digital_only(self, reference: str) -> bool:
            return reference == "20911"

        def fetch_order_line_items(self, reference: str) -> list[object]:
            if reference != "20910":
                return []
            return [
                types.SimpleNamespace(
                    sku="XW-PHYS",
                    name="Physisches Produkt",
                    qty=2,
                    note="Produktbeschreibung",
                )
            ]

    container.register(InvoiceProcessingService, lambda _: _OverviewInvoiceService())
    container.register(WixOrdersClient, lambda _: _OverviewWixClient())
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._summaries = [  # noqa: SLF001
        InvoiceSummary.model_validate(
            {
                "id": "overview-phys",
                "invoiceNumber": "RE-OV-P",
                "status": 100,
                "contact_name": "Phys Kunde",
                "order_reference": "20910",
            }
        ),
        InvoiceSummary.model_validate(
            {
                "id": "overview-digital",
                "invoiceNumber": "RE-OV-D",
                "status": 100,
                "contact_name": "Digital Kunde",
                "order_reference": "20911",
            }
        ),
    ]

    view._refresh_open_invoice_overview()  # noqa: SLF001

    assert view._open_total.text() == "2"  # noqa: SLF001
    assert view._open_with_ref.text() == "2"  # noqa: SLF001
    assert view._open_physical.text() == "0+"  # noqa: SLF001
    qtbot.waitUntil(lambda: view._open_overview_worker is None, timeout=1000)  # noqa: SLF001
    assert view._open_physical.text() == "1"  # noqa: SLF001
    assert view._open_digital.text() == "1"  # noqa: SLF001
    assert view._open_note.text() == "2"  # noqa: SLF001
    assert view._open_plc.text() == "1"  # noqa: SLF001
    products_text = view._open_products_text.toPlainText()  # noqa: SLF001
    assert "2x" in products_text
    assert "Physisches Produkt" in products_text
    assert "XW-PHYS" in products_text
    assert "Produktbeschreibung" in products_text
    assert any(button.toolTip() == "Druckplan/PDF fuer dieses Produkt einrichten" for button in view._gb_open_products.findChildren(QToolButton))  # noqa: SLF001


def test_plc_dialog_defaults_to_direct_webservice_without_changing_list_action(qtbot: object) -> None:
    container = _build_container()
    summary = InvoiceSummary.model_validate(
        {
            "id": "plc-1",
            "invoiceNumber": "RE-PLC-1",
            "status": 200,
            "contact_name": "PLC Customer",
            "order_reference": "20856",
        }
    )
    dialog = PlcLabelPrintDialog(
        container,
        summary,
        address_override_lines=["PLC Customer", "Teststrasse 1", "1030 Wien", "AUSTRIA"],
        recipient_email="customer@example.test",
    )
    qtbot.addWidget(dialog)

    assert dialog._transport_combo.currentData() == "webservice"  # noqa: SLF001
    assert dialog._transport_combo.count() == 2  # noqa: SLF001
    assert dialog._address_edit.toPlainText().endswith("AUSTRIA")  # noqa: SLF001
    assert dialog._recipient_email.text() == "customer@example.test"  # noqa: SLF001


def test_rechnungen_caches_stale_wix_context_result(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    view._wix_context_seq = 2  # noqa: SLF001
    view._on_wix_context_loaded(  # noqa: SLF001
        {
            "seq": 1,
            "__requested_ref": "20899",
            "status": "",
            "meta": {
                "wix_order_number": "20899",
                "wix_customer_email": "kunde@example.test",
            },
            "items": [],
        }
    )

    cached = view._get_cached_wix_context("20899")  # noqa: SLF001
    assert cached is not None
    assert cached["status"] == ""
    assert cached["meta"]["wix_customer_email"] == "kunde@example.test"


def test_rechnungen_applies_persistent_wix_cache_before_background_load(
    qtbot: object,
    monkeypatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "cached-1",
            "invoiceNumber": "RE-CACHED",
            "status": 200,
            "contact_name": "sevDesk Kunde",
            "order_reference": "20899",
        }
    )
    load_calls: list[tuple[str, bool]] = []

    class _CachedWixClient(_FakeWixOrdersClient):
        def get_cached_order_summary(self, reference: str) -> dict[str, str] | None:
            return {
                "wix_order_number": reference,
                "wix_customer_name": "Wix Kunde",
                "wix_customer_email": "wix@example.test",
                "wix_shipping_country": "Austria",
                "wix_shipping_address": "Wix Kunde\nWixstrasse 7\n1010 Wien\nAUSTRIA",
            }

        def get_cached_order_line_items(self, _reference: str) -> list[object] | None:
            return [
                types.SimpleNamespace(
                    sku="XW-CACHE-1",
                    name="Cache Produkt",
                    qty=2,
                    note="",
                    is_unreleased=False,
                )
            ]

    def fake_load_wix_context(order_reference: str, *, show_loading: bool = True) -> None:
        load_calls.append((order_reference, show_loading))

    container.register(WixOrdersClient, lambda _: _CachedWixClient())
    monkeypatch.setattr(view, "_load_wix_context", fake_load_wix_context)

    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001

    qtbot.waitUntil(
        lambda: "Wixstrasse 7" in view._shipping_editor.toPlainText(),  # noqa: SLF001
        timeout=1000,
    )
    assert "Wixstrasse 7" in view._shipping_editor.toPlainText()  # noqa: SLF001
    assert view._wix_customer.text() == "Wix Kunde"  # noqa: SLF001
    assert view._piece_model.rowCount() == 1  # noqa: SLF001
    assert "Cache Produkt" in str(view._piece_model.index(0, 0).data())  # noqa: SLF001
    assert not view._piece_list.isHidden()  # noqa: SLF001
    assert not view._gb_stuecke.isHidden()  # noqa: SLF001
    assert view._get_cached_wix_context("20899") is not None  # noqa: SLF001
    assert load_calls == [("20899", False)]


def test_rechnungen_piece_details_use_model_instead_of_row_widgets(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "pieces",
            "invoiceNumber": "RE-PIECES",
            "invoiceDate": "2026-06-19T00:00:00",
            "status": 1000,
            "sumGross": "20.0",
            "contact_name": "Pieces Customer",
            "order_reference": "20999",
        }
    )
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001

    pieces = [
        PieceBlock(sku=f"XW-{index:03d}", name=f"Produkt {index}", qty_needed=1)
        for index in range(100)
    ]
    view._on_stuecke_loaded({"__requested_ref": "20999", "items": pieces})  # noqa: SLF001

    assert view._piece_model.rowCount() == 100  # noqa: SLF001
    assert view._stuecke_layout.count() == 2  # noqa: SLF001
    assert not view._piece_list.isHidden()  # noqa: SLF001


def test_rechnungen_cached_wix_summary_allows_product_fallback_when_items_missing(
    qtbot: object,
    monkeypatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "cached-missing-items",
            "invoiceNumber": "RE-CACHED-MISSING",
            "status": 200,
            "contact_name": "sevDesk Kunde",
            "order_reference": "20900",
        }
    )
    load_calls: list[tuple[str, bool]] = []

    class _CachedSummaryOnlyWixClient(_FakeWixOrdersClient):
        def get_cached_order_summary(self, reference: str) -> dict[str, str] | None:
            return {
                "wix_order_number": reference,
                "wix_customer_name": "Wix Kunde",
                "wix_customer_email": "wix@example.test",
                "wix_shipping_country": "Austria",
                "wix_shipping_address": "Wix Kunde\nWixstrasse 7\n1010 Wien\nAUSTRIA",
            }

        def get_cached_order_line_items(self, _reference: str) -> list[object] | None:
            return None

    def fake_load_wix_context(order_reference: str, *, show_loading: bool = True) -> None:
        load_calls.append((order_reference, show_loading))

    container.register(WixOrdersClient, lambda _: _CachedSummaryOnlyWixClient())
    monkeypatch.setattr(view, "_load_wix_context", fake_load_wix_context)

    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001

    qtbot.waitUntil(
        lambda: "Wixstrasse 7" in view._shipping_editor.toPlainText(),  # noqa: SLF001
        timeout=1000,
    )
    assert "Wixstrasse 7" in view._shipping_editor.toPlainText()  # noqa: SLF001
    assert view._get_cached_wix_context("20900") is None  # noqa: SLF001
    assert load_calls == [("20900", False)]


def test_rechnungen_load_more_button_stages_drafts_before_open(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    view._active_load_status = 100  # noqa: SLF001
    view._draft_has_more = True  # noqa: SLF001
    view._open_loaded = False  # noqa: SLF001
    view._update_load_more_button()  # noqa: SLF001
    assert view._btn_more.text() == "Weitere Rechnungen laden"  # noqa: SLF001
    assert view._btn_more.isEnabled()  # noqa: SLF001

    view._draft_has_more = False  # noqa: SLF001
    view._update_load_more_button()  # noqa: SLF001
    assert view._btn_more.text() == "Weitere Rechnungen laden"  # noqa: SLF001
    assert view._btn_more.isEnabled()  # noqa: SLF001

    view._active_load_status = 1000  # noqa: SLF001
    view._open_loaded = True  # noqa: SLF001
    view._open_has_more = False  # noqa: SLF001
    view._update_load_more_button()  # noqa: SLF001
    assert view._btn_more.text() == "Keine weiteren"  # noqa: SLF001
    assert not view._btn_more.isEnabled()  # noqa: SLF001


def test_rechnungen_auto_loads_first_open_page_after_drafts(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    draft = InvoiceSummary.model_validate(
        {
            "id": "1",
            "invoiceNumber": "RE-DRAFT",
            "status": 100,
            "contact_name": "Draft Customer",
        }
    )
    calls: list[tuple[int, bool, int | None]] = []

    def fake_start_load(*, limit: int | None = None) -> None:
        calls.append((view._active_load_status, view._append_mode, limit))  # noqa: SLF001

    monkeypatch.setattr(view, "_start_load", fake_start_load)

    view._on_load_result(([draft.as_table_row()], [draft], False, 100))  # noqa: SLF001
    assert view._pending_auto_open_load is True  # noqa: SLF001
    view._on_load_finished()  # noqa: SLF001

    assert calls == [(None, True, 50)]


def test_rechnungen_sorts_staged_loads_by_actuality_descending(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    older_draft = InvoiceSummary.model_validate(
        {
            "id": "11",
            "invoiceNumber": "RE-OLD",
            "invoiceDate": "2026-06-01T00:00:00",
            "status": 100,
            "contact_name": "Older Draft",
        }
    )
    newer_open = InvoiceSummary.model_validate(
        {
            "id": "99",
            "invoiceNumber": "RE-NEW",
            "invoiceDate": "2026-07-01T00:00:00",
            "status": 1000,
            "contact_name": "Newer Open",
        }
    )

    view._apply_load_result_data(  # noqa: SLF001
        [older_draft.as_table_row()],
        [older_draft],
        False,
        100,
        False,
        allow_background_prefetch=False,
    )
    view._apply_load_result_data(  # noqa: SLF001
        [newer_open.as_table_row()],
        [newer_open],
        False,
        1000,
        True,
        allow_background_prefetch=False,
    )

    assert [summary.invoice_number for summary in view._summaries[:2]] == [  # noqa: SLF001
        "RE-NEW",
        "RE-OLD",
    ]


def test_main_window_rechnungen_warms_drafts_but_defers_open_invoice_contexts(
    qtbot: object,
    monkeypatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()

    window._navigate_to(ModuleKey.RECHNUNGEN.value)  # noqa: SLF001
    qtbot.waitUntil(
        lambda: window.page(ModuleKey.RECHNUNGEN) is not None,
        timeout=5000,
    )
    page = window.page(ModuleKey.RECHNUNGEN)
    assert page is not None
    qtbot.waitUntil(lambda: page._rechnungen_view is not None, timeout=5000)  # noqa: SLF001
    view = page._rechnungen_view  # noqa: SLF001
    assert view is not None

    qtbot.waitUntil(
        lambda: (
            view._open_loaded  # noqa: SLF001
            and len(view._summaries) == 2  # noqa: SLF001
        ),
        timeout=5000,
    )

    assert invoice_service.load_calls[:2] == [("status:100", 50, 0), ("recent", 50, 0)]
    qtbot.waitUntil(lambda: view._open_overview_worker is None, timeout=5000)  # noqa: SLF001
    qtbot.waitUntil(
        lambda: view._get_cached_wix_context("20844") is not None,  # noqa: SLF001
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: view._get_cached_wix_context("20845") is not None,  # noqa: SLF001
        timeout=5000,
    )
    assert view._wix_warm_queue == []  # noqa: SLF001

    header = view._table.horizontalHeader()  # noqa: SLF001
    assert not header.stretchLastSection()

    view._table.select_source_row(1)  # noqa: SLF001
    qtbot.waitUntil(
        lambda: (
            "Teststrasse 1" in view._shipping_editor.toPlainText()  # noqa: SLF001
            and view._get_cached_wix_context("20845") is not None  # noqa: SLF001
        ),
        timeout=1000,
    )

    view._table.select_source_row(0)  # noqa: SLF001
    view._table.select_source_row(1)  # noqa: SLF001

    assert view._dl_number.text() == "RE-OPEN"  # noqa: SLF001
    qtbot.waitUntil(
        lambda: "Teststrasse 1" in view._shipping_editor.toPlainText(),  # noqa: SLF001
        timeout=1000,
    )
    assert "Teststrasse 1" in view._shipping_editor.toPlainText()  # noqa: SLF001
    assert invoice_service.load_calls == [("status:100", 50, 0), ("recent", 50, 0)]


def test_rechnungen_detail_panel_click_does_not_clear_selection(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view.resize(1100, 700)
    view.show()
    qtbot.waitExposed(view)

    detail_pos = view._detail_scroll.mapToGlobal(view._detail_scroll.rect().center())  # noqa: SLF001
    table_pos = view._table.mapToGlobal(view._table.rect().center())  # noqa: SLF001
    outside_pos = view._btn_more.mapToGlobal(view._btn_more.rect().center())  # noqa: SLF001

    assert view._should_clear_selection_for_global_pos(detail_pos) is False  # noqa: SLF001
    assert view._should_clear_selection_for_global_pos(table_pos) is False  # noqa: SLF001
    assert view._should_clear_selection_for_global_pos(outside_pos) is True  # noqa: SLF001


def test_rechnungen_mollie_alert_button_visibility(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    view.update_mollie_alert_count(0)  # noqa: SLF001
    assert view._mollie_alert_count == 0  # noqa: SLF001

    view.update_mollie_alert_count(3)  # noqa: SLF001
    assert view._mollie_alert_count == 3  # noqa: SLF001


def test_custom_label_dialog_opens_even_when_print_status_is_unknown(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    called = {"count": 0}

    def fake_exec(self) -> int:
        called["count"] += 1
        return 0

    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.view._CustomLabelDialog.exec", fake_exec)

    view._print_allowed = False  # noqa: SLF001
    view._on_custom_label_clicked()  # noqa: SLF001

    assert called["count"] == 1
