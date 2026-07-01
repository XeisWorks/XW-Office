"""Smoke tests for the Rechnungen daily-business view."""
from __future__ import annotations

import sys
import types

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.core.types import ModuleKey
from xw_studio.services.daily_business.service import DailyBusinessService
from xw_studio.services.inventory.service import StartMode, StartPreflight
from xw_studio.services.invoice_processing.service import InvoiceProcessingService
from xw_studio.services.products.print_decision import PrintDecisionEngine
from xw_studio.services.secrets.service import SecretService
from xw_studio.services.sendungen.service import OffeneSendungenService
from xw_studio.services.sevdesk.invoice_client import InvoiceSummary
from xw_studio.services.wix.client import WixOrdersClient
from xw_studio.ui.main_window import MainWindow
from xw_studio.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView, _StartDialog
from xw_studio.ui.modules.rechnungen.plc_label_dialog import PlcLabelPrintDialog
from xw_studio.ui.modules.rechnungen.view import RechnungenView, _ActionsDelegate


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


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
        self.load_calls: list[tuple[int, int, int]] = []
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
                "status": 200,
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
        self.load_calls.append((status, limit, offset))
        summaries = [self._draft] if status == 100 else [self._open]
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


def _build_rechnungen_test_container() -> tuple[Container, _FakeInvoiceProcessingService]:
    container = _build_container()
    invoice_service = _FakeInvoiceProcessingService()
    container.register(SecretService, lambda _: _FakeSecretService())
    container.register(InvoiceProcessingService, lambda _: invoice_service)
    container.register(WixOrdersClient, lambda _: _FakeWixOrdersClient())
    container.register(PrintDecisionEngine, lambda _: _FakePrintDecisionEngine())
    container.register(DailyBusinessService, lambda _: _FakeDailyBusinessService())
    container.register(OffeneSendungenService, lambda _: _FakeOffeneSendungenService())
    return container, invoice_service


def test_tagesgeschaeft_contains_rechnungen_view(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
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
    assert not view._btn_stop.isEnabled()  # noqa: SLF001


def test_tagesgeschaeft_alert_buttons_follow_counts(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)

    view._update_alert_button(view._btn_sendungen_alert, "OFFENE SENDUNGEN", 0)  # noqa: SLF001
    assert view._btn_sendungen_alert.isHidden()  # noqa: SLF001

    view._update_alert_button(view._btn_sendungen_alert, "OFFENE SENDUNGEN", 2)  # noqa: SLF001

    assert view._btn_sendungen_alert.text() == "OFFENE SENDUNGEN (2)"  # noqa: SLF001
    assert not view._btn_sendungen_alert.isHidden()  # noqa: SLF001


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
    monkeypatch.setattr(view, "_open_customer_mail_outlook", lambda _email, _subject: False)

    summary = invoice_service._draft  # noqa: SLF001
    view._open_customer_mail_url(summary, "customer-20844@example.test")  # noqa: SLF001

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


def test_customer_mail_uses_configured_outlook_sender(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    class _Account:
        SmtpAddress = "office@xeisworks.at"
        DisplayName = "XeisWorks"
        UserName = "office@xeisworks.at"

    class _Accounts:
        Count = 1

        def __iter__(self):  # type: ignore[no-untyped-def]
            return iter([_Account()])

        def Item(self, index: int) -> _Account:  # noqa: N802
            assert index == 1
            return _Account()

    class _Ole:
        def __init__(self) -> None:
            self.invocations: list[tuple[object, ...]] = []

        def Invoke(self, *args: object) -> None:  # noqa: N802
            self.invocations.append(args)

    class _Mail:
        def __init__(self) -> None:
            self._send_using_account = None
            self.To = ""
            self.Subject = ""
            self.displayed = False
            self.account_set_count = 0
            self._oleobj_ = _Ole()

        @property
        def SendUsingAccount(self) -> object:
            return self._send_using_account

        @SendUsingAccount.setter
        def SendUsingAccount(self, account: object) -> None:
            self.account_set_count += 1
            self._send_using_account = account

        def Display(self, modal: bool) -> None:  # noqa: N802
            assert modal is False
            self.displayed = True

    mail = _Mail()
    outlook = types.SimpleNamespace(
        Session=types.SimpleNamespace(Accounts=_Accounts()),
        CreateItem=lambda _kind: mail,
    )
    win32com_client = types.SimpleNamespace(Dispatch=lambda _name: outlook)
    pythoncom = types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None)
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=win32com_client))
    monkeypatch.setitem(sys.modules, "win32com.client", win32com_client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)

    summary = invoice_service._draft  # noqa: SLF001

    assert view._open_customer_mail_outlook("kunde@example.test", view._customer_mail_subject(summary)) is True  # noqa: SLF001
    assert mail.SendUsingAccount.SmtpAddress == "office@xeisworks.at"
    assert mail.account_set_count == 2
    assert len(mail._oleobj_.invocations) == 2
    assert mail._oleobj_.invocations[0][:4] == (64209, 0, 8, 0)
    assert mail.To == "kunde@example.test"
    assert mail.Subject == "Best.-Nr. 20844 | RE-DRAFT"
    assert mail.displayed is True


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

    view._active_load_status = 200  # noqa: SLF001
    view._open_loaded = True  # noqa: SLF001
    view._open_has_more = False  # noqa: SLF001
    view._update_load_more_button()  # noqa: SLF001
    assert view._btn_more.text() == "Keine weiteren"  # noqa: SLF001
    assert not view._btn_more.isEnabled()  # noqa: SLF001


def test_rechnungen_auto_loads_first_open_page_after_drafts(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
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

    assert calls == [(200, True, 30)]


def test_main_window_rechnungen_warms_drafts_but_defers_open_invoice_contexts(
    qtbot: object,
    monkeypatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    monkeypatch.setattr("xw_studio.ui.main_window.discover_printers", lambda: [])
    monkeypatch.setattr("xw_studio.ui.modules.rechnungen.view.discover_printers", lambda: [])
    window = MainWindow(container)
    qtbot.addWidget(window)
    window.show()

    window._navigate_to(ModuleKey.RECHNUNGEN.value)  # noqa: SLF001
    page = window._pages[ModuleKey.RECHNUNGEN.value]  # noqa: SLF001
    view = page._rechnungen_view  # noqa: SLF001

    qtbot.waitUntil(
        lambda: (
            view._open_loaded  # noqa: SLF001
            and len(view._summaries) == 2  # noqa: SLF001
        ),
        timeout=5000,
    )

    assert invoice_service.load_calls[:2] == [(100, 50, 0), (200, 30, 0)]
    assert view._open_overview_worker is None  # noqa: SLF001
    qtbot.waitUntil(
        lambda: view._get_cached_wix_context("20844") is not None,  # noqa: SLF001
        timeout=5000,
    )
    assert view._get_cached_wix_context("20845") is None  # noqa: SLF001
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

    assert "Teststrasse 1" in view._shipping_editor.toPlainText()  # noqa: SLF001
    assert invoice_service.load_calls == [(100, 50, 0), (200, 30, 0)]


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
