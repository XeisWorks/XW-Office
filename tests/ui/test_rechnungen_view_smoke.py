"""Smoke tests for the Rechnungen daily-business view."""
from __future__ import annotations

from decimal import Decimal
from threading import Event, Timer, get_ident
from time import perf_counter
import types
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QPoint, Qt, QTimer
from pytest import MonkeyPatch
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QMessageBox, QSpinBox, QToolButton

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig, InventorySection
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.core.types import ModuleKey
from xw_office.core.worker import BackgroundWorker
from xw_office.services.b2b_credit import B2bCreditService
from xw_office.models.customer_aftercare import CustomerAftercareCase
from xw_office.repositories.customer_aftercare import CustomerAftercareReservation
from xw_office.services.customer_aftercare.redelivery import (
    CustomerAftercareRedeliveryService,
    RedeliveryContext,
)
from xw_office.services.daily_business.service import DailyBusinessService
from xw_office.services.digital_licenses import DigitalLicenseService
from xw_office.services.draft_invoice.service import DraftInvoiceService, ProductPreflightPlan
from xw_office.services.inventory.service import StartDecision, StartMode, StartPreflight
from xw_office.services.invoice_processing.context import InvoiceWorkContext, InvoiceWorkPosition
from xw_office.services.invoice_processing.service import InvoiceProcessingService
from xw_office.services.invoice_processing.start_holds import StartHold
from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.products.catalog import Product, ProductCatalogService, StockStatus
from xw_office.services.products.print_decision import (
    PieceBlock,
    PrintDecisionEngine,
)
from xw_office.services.secrets.service import SecretService
from xw_office.services.sendungen.service import OffeneSendungenService
from xw_office.services.transfers.service import OffeneUeberweisungenService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary
from xw_office.services.wix.client import WixOrdersClient
from xw_office.ui.main_window import MainWindow
from xw_office.ui.modules.rechnungen.open_invoice_overview import (
    BuyerNote,
    OpenInvoiceOverview,
    PrintProductAggregate,
    UnreleasedAssignment,
)
from xw_office.ui.modules.rechnungen.tagesgeschaeft_view import TagesgeschaeftView, _StartDialog
from xw_office.ui.modules.rechnungen.plc_label_dialog import (
    PlcLabelPrintDialog,
    _PlcDialogContext,
)
from xw_office.ui.modules.rechnungen.view import (
    RechnungenView,
    _ActionsDelegate,
    _DraftInvoiceDialog,
)
from xw_office.ui.dialogs.unreleased_title_dialog import UnreleasedTitleDecision


def _build_container(*, start_stock_booking_enabled: bool = False) -> Container:
    cfg = AppConfig(
        inventory=InventorySection(start_stock_booking_enabled=start_stock_booking_enabled)
    )
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def _wait_embedded_rechnungen(qtbot: object, view: TagesgeschaeftView) -> RechnungenView:
    qtbot.waitUntil(lambda: view._rechnungen_view is not None, timeout=3000)  # type: ignore[attr-defined]  # noqa: SLF001
    assert view._rechnungen_view is not None  # noqa: SLF001
    return view._rechnungen_view  # noqa: SLF001


def test_cached_invoice_piece_is_hydrated_before_product_panel_render(
    qtbot: object,
    monkeypatch: object,
    tmp_path: object,
) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    pdf_path = tmp_path / "cached-piece.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    cached_piece = PieceBlock(
        sku="XW-010",
        name="Vielen Dank für die Blumen",
        qty_needed=1,
    )

    def hydrate(_catalog: object, piece: PieceBlock) -> PieceBlock:
        piece.product = Product(
            id="canonical",
            sku=piece.sku,
            name=piece.name,
            print_file_path=str(pdf_path),
        )
        piece.print_plan = [{"range": "Alle Seiten", "profile_id": "noten_a5"}]
        return piece

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.resolve_piece_print_config", hydrate)

    view._on_stuecke_loaded([cached_piece])  # noqa: SLF001

    qtbot.waitUntil(lambda: view._current_piece_blocks == [cached_piece], timeout=2000)  # noqa: SLF001
    assert view._current_piece_blocks == [cached_piece]  # noqa: SLF001
    assert cached_piece.print_file_path == pdf_path
    assert cached_piece.has_direct_print_config is True


def test_unreleased_catalog_disk_and_settings_read_runs_off_ui_thread(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container = _build_container()
    catalog = container.resolve(ProductCatalogService)
    view = RechnungenView(container)
    qtbot.addWidget(view)
    entered, release, heartbeat = Event(), Event(), Event()

    def blocked_load() -> list[object]:
        entered.set()
        assert release.wait(3)
        return []

    monkeypatch.setattr(catalog, "_load_unreleased_products", blocked_load)
    piece = PieceBlock(sku="SKU-1", name="Titel", qty_needed=1)
    view._on_stuecke_loaded([piece])  # noqa: SLF001
    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        assert catalog.unreleased_products_loaded is False
    finally:
        release.set()

    qtbot.waitUntil(lambda: view._current_piece_blocks == [piece], timeout=3000)  # noqa: SLF001
    assert catalog.unreleased_products_loaded is True


def test_cold_product_catalog_resolution_runs_off_ui_thread(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    container.reset()
    main_thread_id = get_ident()
    original_resolve = container.resolve
    entered, release, heartbeat = Event(), Event(), Event()

    def checked_resolve(service_type: type[object]) -> object:
        if service_type is ProductCatalogService and container.get_if_resolved(ProductCatalogService) is None:
            entered.set()
            assert get_ident() != main_thread_id
            assert release.wait(3)
        return original_resolve(service_type)

    monkeypatch.setattr(container, "resolve", checked_resolve)
    piece = PieceBlock(sku="SKU-COLD", name="Titel", qty_needed=1)
    view._on_stuecke_loaded([piece])  # noqa: SLF001
    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        assert view._piece_model.rowCount() == 0  # noqa: SLF001
    finally:
        release.set()

    qtbot.waitUntil(lambda: view._current_piece_blocks == [piece], timeout=3000)  # noqa: SLF001
    catalog = container.get_if_resolved(ProductCatalogService)
    assert catalog is not None
    assert catalog.unreleased_products_loaded is True


def test_add_unreleased_product_updates_the_analysis_row_before_print_configuration(
    qtbot: object,
    monkeypatch: object,
) -> None:
    """Saving an XW-010 title must be visible while its print dialog is open."""
    container, _invoice_service = _build_rechnungen_test_container()
    catalog = container.resolve(ProductCatalogService)
    view = RechnungenView(container)
    qtbot.addWidget(view)
    item = PrintProductAggregate(
        sku="XW-010",
        title="Kundenangabe aus Wix",
        description="Besetzung: Flöte",
        quantity=1,
    )
    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="unreleased-title-refresh",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[item],
        )
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedProductEditDialog.exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedProductEditDialog.get_data",
        lambda _dialog: ("Kanonischer Titel", "Blasmusik", ["Kundenangabe aus Wix"]),
    )
    configured: list[bool] = []
    errors: list[str] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog._configure_missing_piece_print",
        lambda *_args, **_kwargs: configured.append(True),
    )
    monkeypatch.setattr(view, "_refresh_open_invoice_overview", lambda: None)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args: errors.append(str(_args[-1]) if _args else "warning"),
    )
    entered, release, heartbeat = Event(), Event(), Event()
    fallback_release = Timer(5, release.set)
    fallback_release.start()
    original_resolve = catalog.resolve_unreleased_title
    heartbeat_timer = QTimer(view)
    heartbeat_timer.setInterval(5)
    heartbeat_timer.timeout.connect(heartbeat.set)
    heartbeat_timer.start()

    def blocked_resolve(title: str) -> object:
        entered.set()
        assert release.wait(10)
        return original_resolve(title)

    monkeypatch.setattr(catalog, "resolve_unreleased_title", blocked_resolve)

    assert view._create_unreleased_product_from_alias(  # noqa: SLF001
        raw_title=item.title,
        quantity=item.quantity,
        note=item.description,
    ) is None

    try:
        qtbot.waitUntil(entered.is_set, timeout=1000)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
    finally:
        heartbeat_timer.stop()
        fallback_release.cancel()
        release.set()

    qtbot.waitUntil(lambda: bool(configured) or bool(errors), timeout=3000)
    assert not errors, errors

    assert catalog.resolve_unreleased_title(item.title).canonical_name == "Kanonischer Titel"
    visible_labels = [label.text() for label in view._gb_open_products.findChildren(QLabel)]  # noqa: SLF001
    assert "Kanonischer Titel" in visible_labels
    assert "Kundenangabe: Kundenangabe aus Wix" in visible_labels


def test_start_unreleased_product_creation_resumes_after_catalog_commit(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    catalog = container.resolve(ProductCatalogService)
    catalog.list_unreleased_products()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    configured: list[str] = []
    completed: list[tuple[bool, str]] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedTitleDialog.decision",
        lambda _dialog: UnreleasedTitleDecision(
            raw_title="Wix-Neuanlage-Alias",
            canonical_name="",
            owner="",
            create_product=True,
        ),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedProductEditDialog.exec",
        lambda _dialog: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedProductEditDialog.get_data",
        lambda _dialog: ("Neues Werk aus START", "Blasmusik", ["Wix-Neuanlage-Alias"]),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog._configure_missing_piece_print",
        lambda _owner, _container, piece: configured.append(piece.name),
    )
    monkeypatch.setattr(view, "_refresh_open_invoice_overview", lambda: None)

    view.clarify_unreleased_start_issues(
        [
            types.SimpleNamespace(
                raw_title="Wix-Neuanlage-Alias",
                wix_order_number="21549",
                quantity=1,
                wix_description="",
            )
        ],
        on_complete=lambda ok, error: completed.append((ok, error)),
    )

    qtbot.waitUntil(lambda: bool(completed), timeout=3000)
    assert completed == [(True, "")]
    assert configured == ["Neues Werk aus START"]
    assert catalog.resolve_unreleased_title("Wix-Neuanlage-Alias").canonical_name == "Neues Werk aus START"


def test_start_clarifies_same_unreleased_alias_only_once_across_invoices(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    container.resolve(ProductCatalogService).list_unreleased_products()
    clarified: list[tuple[str, str]] = []
    completions: list[tuple[bool, str]] = []
    issues = [
        types.SimpleNamespace(
            raw_title="Gleicher Wix-Alias",
            wix_order_number="21549",
            quantity=1,
            wix_description="",
        ),
        types.SimpleNamespace(
            raw_title="Gleicher Wix-Alias",
            wix_order_number="21550",
            quantity=1,
            wix_description="",
        ),
    ]

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.UnreleasedTitleDialog.decision",
        lambda _dialog: UnreleasedTitleDecision(
            raw_title="Gleicher Wix-Alias",
            canonical_name="Kanonisches Werk",
            owner="Albert",
        ),
    )

    def persist(write: object, done: object) -> None:
        del write
        done(True, "", None)  # type: ignore[operator]

    monkeypatch.setattr(view, "_run_unreleased_settings_write", persist)
    monkeypatch.setattr(
        view,
        "_split_unreleased_piece",
        lambda piece, _catalog, order_reference: clarified.append(
            (piece.name, order_reference)
        ) or [piece],
    )

    view.clarify_unreleased_start_issues(
        issues,
        on_complete=lambda ok, error: completions.append((ok, error)),
    )

    assert clarified == [("Gleicher Wix-Alias", "21549")]
    assert completions == [(True, "")]


def test_unreleased_settings_write_runs_off_ui_thread_and_reports_after_commit(
    qtbot: QtBot,
) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    entered = Event()
    release = Event()
    committed = Event()
    heartbeat: list[bool] = []
    result: list[tuple[bool, str, object]] = []

    def blocked_write() -> str:
        entered.set()
        release.wait(timeout=2)
        committed.set()
        return "saved"

    view._run_unreleased_settings_write(  # noqa: SLF001
        blocked_write,
        lambda ok, error, payload: result.append((ok, error, payload)),
    )
    assert entered.wait(timeout=1)
    assert view._table.isEnabled() is False  # noqa: SLF001
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    qtbot.waitUntil(lambda: bool(heartbeat), timeout=500)
    assert result == []

    release.set()
    qtbot.waitUntil(lambda: bool(result), timeout=2000)
    assert committed.is_set()
    assert result == [(True, "", "saved")]
    assert view._table.isEnabled() is True  # noqa: SLF001


def test_start_product_preflight_continues_only_after_unreleased_commit(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    view = TagesgeschaeftView(_build_container())
    qtbot.addWidget(view)
    completion: list[object] = []
    continued: list[ProductPreflightPlan] = []

    class _RechnungenView:
        def clarify_unreleased_start_issues(
            self,
            _issues: object,
            *,
            on_complete: object,
            should_abort: object,
        ) -> None:
            del should_abort
            completion.append(on_complete)

    plan = ProductPreflightPlan(
        issues=[],
        part_categories=[],
        unreleased_titles=(types.SimpleNamespace(raw_title="Wix-Alias"),),
    )
    view._rechnungen_view = _RechnungenView()  # type: ignore[assignment]  # noqa: SLF001
    monkeypatch.setattr(
        view,
        "_continue_start_product_preflight",
        lambda ready_plan, _elapsed: continued.append(ready_plan),
    )

    view._on_start_product_preflight_ready(plan)  # noqa: SLF001
    assert continued == []
    assert len(completion) == 1

    callback = completion[0]
    callback(True, "")  # type: ignore[operator]
    assert continued == [plan]


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
        self.last_start_overview: dict[str, object] = {}
        self.run_print_calls: list[tuple[list[str], bool]] = []
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

    def export_invoice_preview_pdf(self, invoice_id: str, target_dir: str) -> Path:
        target = Path(target_dir) / f"{invoice_id}.pdf"
        target.write_bytes(b"%PDF-1.4 preview")
        return target

    def read_last_start_overview(self) -> dict[str, object]:
        return dict(self.last_start_overview)

    def write_last_start_overview(self, payload: dict[str, object]) -> None:
        self.last_start_overview = dict(payload)

    def print_run_documents(self, invoice_ids: list[str], *, labels: bool) -> dict[str, object]:
        self.run_print_calls.append((list(invoice_ids), labels))
        return {
            "kind": "labels" if labels else "invoices",
            "requested": len(invoice_ids),
            "printed": len(invoice_ids),
            "failures": [],
        }


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
    def acquire_product_print_claim(self, piece: PieceBlock) -> object:
        return types.SimpleNamespace(
            invoice_id=piece.sku,
            operation="physical_product_print",
            operation_id=f"test:{piece.sku}",
            state="running",
            acquired=True,
        )

    def finish_product_print_claim(
        self, _claim: object, _state: str, *, error: str = ""
    ) -> bool:
        return True

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


class _FakeDigitalLicenseService:
    def open_count(self, *, limit: int = 30, use_cache: bool = True) -> int:
        del limit, use_cache
        return 0

    def list_open_cases(self, *, limit: int = 100, use_cache: bool = False) -> list[object]:
        del limit, use_cache
        return []


def _build_rechnungen_test_container() -> tuple[Container, _FakeInvoiceProcessingService]:
    container = _build_container()
    invoice_service = _FakeInvoiceProcessingService()
    container.register(SecretService, lambda _: _FakeSecretService())
    container.register(InvoiceProcessingService, lambda _: invoice_service)
    container.register(WixOrdersClient, lambda _: _FakeWixOrdersClient())
    container.register(PrintDecisionEngine, lambda _: _FakePrintDecisionEngine())
    container.register(DailyBusinessService, lambda _: _FakeDailyBusinessService())
    container.register(OffeneSendungenService, lambda _: _FakeOffeneSendungenService())
    container.register(DigitalLicenseService, lambda _: _FakeDigitalLicenseService())  # type: ignore[arg-type,return-value]
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


def test_rechnungen_shutdown_tracks_redelivery_workers(qtbot: object) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    prepare_worker = BackgroundWorker(lambda: None)
    apply_worker = BackgroundWorker(lambda: None)

    view._redelivery_prepare_worker = prepare_worker  # noqa: SLF001
    view._redelivery_apply_worker = apply_worker  # noqa: SLF001

    assert prepare_worker in view._shutdown_workers()  # noqa: SLF001
    assert apply_worker in view._shutdown_workers()  # noqa: SLF001


def test_late_redelivery_result_is_ignored_during_shutdown(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    entered, release = Event(), Event()
    case = CustomerAftercareCase(id=uuid4(), source_message_id="shutdown-redelivery")
    context = RedeliveryContext(
        reservation=CustomerAftercareReservation(state="created", case=case),
        case=case,
        items=(),
        address_lines=(),
        address_source="",
        wix_contact_id="",
        sevdesk_contact_id="",
        customer_email="",
    )

    class SlowRedelivery:
        def prepare_from_invoice(self, _summary: InvoiceSummary) -> RedeliveryContext:
            entered.set()
            assert release.wait(3)
            return context

    container.register(CustomerAftercareRedeliveryService, lambda _: SlowRedelivery())  # type: ignore[arg-type,return-value]
    opened: list[bool] = []
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.RedeliveryDialog.exec",
        lambda _dialog: (opened.append(True), QDialog.DialogCode.Rejected)[1],
    )
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._open_redelivery_popup(invoice_service._draft)  # noqa: SLF001

    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        assert view.prepare_shutdown() is False
    finally:
        release.set()

    qtbot.waitUntil(view.shutdown_complete, timeout=3000)
    assert opened == []


def test_late_invoice_list_and_badge_callbacks_are_ignored_during_shutdown(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    view._shutting_down = True  # noqa: SLF001
    view._on_load_error(RuntimeError("late list failure"))  # noqa: SLF001
    view._on_search_error(RuntimeError("late search failure"))  # noqa: SLF001
    view._on_inventory_alert_error(RuntimeError("late badge failure"))  # noqa: SLF001
    view._on_mollie_badge_result(  # noqa: SLF001
        {"mollie": 4, "sendungen": 3, "drucke": 2, "digital_licenses": 1}
    )
    view._on_inventory_alert_count(9)  # noqa: SLF001

    assert warnings == []
    assert view._mollie_alert_count == 0  # noqa: SLF001
    assert view._sendungen_alert_count == 0  # noqa: SLF001
    assert view._drucke_alert_count == 0  # noqa: SLF001
    assert view._digital_licenses_alert_count == 0  # noqa: SLF001
    assert view._btn_inventory_alert.isHidden()  # noqa: SLF001


def test_late_pdf_mail_and_delete_callbacks_do_not_open_ui_on_shutdown(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    dialogs: list[str] = []
    opened_urls: list[object] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, _message: dialogs.append(str(title)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, _message: dialogs.append(str(title)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, _message: dialogs.append(str(title)),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    view._shutting_down = True  # noqa: SLF001
    view._on_invoice_pdf_preview_result({"path": "late-preview.pdf"})  # noqa: SLF001
    view._on_invoice_pdf_preview_error(RuntimeError("late PDF failure"))  # noqa: SLF001
    view._on_customer_mail_ready(invoice_service._draft, {"email": ""})  # noqa: SLF001
    view._on_customer_mail_error(RuntimeError("late mail failure"))  # noqa: SLF001
    view._on_delete_draft_result({"label": "late draft"})  # noqa: SLF001
    view._on_delete_draft_error(RuntimeError("late delete failure"))  # noqa: SLF001
    view._on_print_run_output_result(  # noqa: SLF001
        {"requested": 1, "printed": 0, "failures": [{"error": "late print"}]}
    )
    view._on_print_run_output_error(RuntimeError("late print failure"))  # noqa: SLF001
    view._on_fulfillment_step_result({"invoice": "RE-LATE"})  # noqa: SLF001
    view._on_fulfillment_step_error(RuntimeError("late fulfillment failure"))  # noqa: SLF001
    view._on_direct_label_print_error(RuntimeError("late label failure"))  # noqa: SLF001
    view._on_direct_invoice_print_error(RuntimeError("late invoice failure"))  # noqa: SLF001
    view._on_send_invoice_error(RuntimeError("late send failure"))  # noqa: SLF001
    view._on_create_draft_error(RuntimeError("late draft failure"))  # noqa: SLF001
    view._on_product_print_error(RuntimeError("late product print failure"))  # noqa: SLF001

    assert dialogs == []
    assert opened_urls == []


def test_shutdown_finished_callbacks_do_not_start_followup_work(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    view._shutting_down = True  # noqa: SLF001
    started: list[str] = []
    monkeypatch.setattr(view, "_submit_side_job", lambda **_kwargs: started.append("overview"))
    monkeypatch.setattr(
        view,
        "_ensure_open_product_preparation",
        lambda _overview: started.append("product-preparation"),
    )
    monkeypatch.setattr(view, "_start_next_run_output_print", lambda: started.append("run-print"))
    monkeypatch.setattr(view, "_start_next_hint_prefetch", lambda: started.append("hint-prefetch"))
    view._pending_open_overview_rows = [InvoiceSummary.model_validate({"id": "1"})]  # noqa: SLF001
    view._open_product_preparation_pending = object()  # noqa: SLF001
    view._run_output_pending_requests.append(object())  # type: ignore[arg-type]  # noqa: SLF001
    view._hint_draft_queue = ["20844"]  # noqa: SLF001

    class Signal:
        def connect(self, _callback: object) -> None:
            pass

    class FakeWorker:
        def __init__(self, _job: object) -> None:
            self.signals = types.SimpleNamespace(result=Signal(), error=Signal(), finished=Signal())

        def start(self) -> None:
            started.append("draft-create")

    class FakePreviewDialog:
        def set_preview_result(self, _message: str, *, ok: bool) -> None:
            started.append(f"preview:{ok}")

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.BackgroundWorker", FakeWorker)

    view._on_open_overview_finished()  # noqa: SLF001
    view._on_open_product_preparation_finished()  # noqa: SLF001
    view._on_print_run_output_finished()  # noqa: SLF001
    view._on_hint_prefetch_finished()  # noqa: SLF001
    view._on_draft_product_plan_ready(  # noqa: SLF001
        ProductPreflightPlan(issues=[], part_categories=[])
    )
    preview_dialog = FakePreviewDialog()
    view._on_draft_preview_result(preview_dialog, object())  # noqa: SLF001
    view._on_draft_preview_error(preview_dialog, RuntimeError("late preview"))  # noqa: SLF001

    assert started == []


def test_start_hold_table_toggle_persists_without_blocking_the_ui(
    qtbot: QtBot, monkeypatch: MonkeyPatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft.model_copy(update={"id": "hold-table-1"})  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    entered = Event()
    release = Event()
    holds: dict[str, StartHold] = {}

    class _Service:
        def get_start_hold(self, invoice_id: str) -> StartHold | None:
            return holds.get(invoice_id)

        def defer_invoice_from_start(self, invoice_id: str, reason: str, **kwargs: object) -> StartHold:
            entered.set()
            release.wait(timeout=2)
            hold = StartHold.create(
                invoice_id,
                reason,
                note=str(kwargs.get("note") or ""),
                review_on=str(kwargs.get("review_on") or ""),
            )
            holds[invoice_id] = hold
            return hold

        def list_start_holds(self) -> dict[str, StartHold]:
            return dict(holds)

    service = _Service()
    monkeypatch.setattr(container, "resolve", lambda _service_type: service)

    class _HoldDialog:
        reason = "customer_question"
        note = "Rueckfrage offen"
        review_on = ""

        def __init__(self, **_kwargs: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.StartHoldDialog", _HoldDialog
    )
    heartbeat = {"ticks": 0}
    timer = QTimer(view)
    timer.timeout.connect(lambda: heartbeat.__setitem__("ticks", heartbeat["ticks"] + 1))
    timer.start(1)

    view._toggle_start_hold(summary, expected_checked=True)  # noqa: SLF001
    qtbot.waitUntil(entered.is_set)
    qtbot.wait(20)
    assert heartbeat["ticks"] > 0
    release.set()
    qtbot.waitUntil(lambda: view._start_hold_worker is None)  # noqa: SLF001
    timer.stop()

    assert holds[summary.id].reason == "customer_question"
    row = view._table.source_rows_data()[0]  # noqa: SLF001
    assert row["__start_checked__"] is False
    assert "Kundenklärung" in row["__tooltip__START"]


def test_tagesgeschaeft_contains_rechnungen_view(qtbot: object) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)
    assert hasattr(view, "_rechnungen_view")  # noqa: SLF001
    assert view._btn_start.text() == "START"  # noqa: SLF001
    assert view._btn_start.menu() is None  # noqa: SLF001
    assert view._rechnungen_view._table.model().headerData(  # noqa: SLF001
        9, Qt.Orientation.Horizontal
    ) == "START"
    assert view._btn_refresh.text() == ""  # noqa: SLF001
    assert not view._btn_refresh.icon().isNull()  # noqa: SLF001
    assert view._btn_draft.text() == "Entwurf"  # noqa: SLF001
    assert view._btn_label_menu.text() == ""  # noqa: SLF001
    assert [action.text() for action in view._btn_label_menu.menu().actions()] == [  # noqa: SLF001
        "Custom-Label …",
        "PLC-Label …",
    ]
    assert view._btn_statistics.text() == ""  # noqa: SLF001
    assert not view._btn_statistics.icon().isNull()  # noqa: SLF001
    assert view._btn_stop.text() == "STOP"  # noqa: SLF001
    assert not view._btn_stop.isEnabled()  # noqa: SLF001
    assert not view._rechnungen_view._toolbar.isVisible()  # noqa: SLF001
    bar_layout = view._btn_start.parentWidget().layout()  # noqa: SLF001
    widgets = [bar_layout.itemAt(i).widget() for i in range(bar_layout.count())]
    assert widgets.index(view._btn_label_menu) == widgets.index(view._btn_statistics) - 1  # noqa: SLF001
    assert widgets.index(view._btn_statistics) == widgets.index(view._btn_special_order) - 1  # noqa: SLF001
    assert widgets.index(view._btn_start) == widgets.index(view._btn_stop) - 1  # noqa: SLF001
    for alert_button in (
        view._btn_sendungen_alert,
        view._btn_digital_licenses_alert,
        view._btn_transfer_alert,
        view._btn_mollie_alert,
        view._btn_lieferkorrektur_review_alert,
        view._btn_lieferkorrektur_due_alert,
    ):
        assert alert_button.parentWidget() is view._btn_start.parentWidget()  # noqa: SLF001
    assert not hasattr(view, "_btn_beenden")


def test_start_click_disables_start_immediately(qtbot: object, monkeypatch) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    _wait_embedded_rechnungen(qtbot, view)
    started = {"value": False}

    def fake_start(self) -> None:
        started["value"] = True

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.tagesgeschaeft_view.BackgroundWorker.start",
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


def test_actions_delegate_exposes_customs_and_mail_actions() -> None:
    layout = _ActionsDelegate._layout(width=120, height=28)  # noqa: SLF001
    assert [key for key, _x, _size in layout] == ["post", "customs", "wix", "mail"]
    customs_key, customs_x, customs_size = layout[1]
    assert _ActionsDelegate.action_at_x(customs_x + customs_size / 2, width=120, height=28) == customs_key
    mail_key, mail_x, mail_size = layout[-1]
    assert _ActionsDelegate.action_at_x(mail_x + mail_size / 2, width=120, height=28) == mail_key


def test_actions_delegate_keeps_dark_theme_icons_visible(qtbot: object) -> None:
    delegate = _ActionsDelegate()
    redelivery = delegate._rendered_icon_for_key("redelivery", 18)  # noqa: SLF001
    post = delegate._rendered_icon_for_key("post", 18)  # noqa: SLF001

    assert redelivery is not None and not redelivery.isNull()
    redelivery_image = redelivery.toImage()
    visible_pixels = [
        redelivery_image.pixelColor(x, y)
        for y in range(redelivery_image.height())
        for x in range(redelivery_image.width())
        if redelivery_image.pixelColor(x, y).alpha() >= 220
    ]
    assert visible_pixels
    # Redelivery deliberately uses violet: it remains distinct from the
    # yellow PLC and blue customs symbols in the same compact cell.
    assert max(color.red() for color in visible_pixels) >= 180
    assert max(color.blue() for color in visible_pixels) >= 240
    assert max(color.green() for color in visible_pixels) < 180

    # All symbols are generated as square vector artwork, so source-image
    # margins and downscaling cannot distort them.
    assert post is not None and not post.isNull()
    assert post.width() == 18
    assert post.height() == 18


def test_customer_mail_action_opens_classic_outlook_draft(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    opened: list[dict[str, str]] = []

    def fake_open_classic_outlook_draft(
        *,
        to_email: str,
        subject: str,
        sender_smtp: str,
    ) -> dict[str, str]:
        opened.append({"to": to_email, "subject": subject, "sender": sender_smtp})
        return {"pid": "123"}

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.open_classic_outlook_draft",
        fake_open_classic_outlook_draft,
    )

    summary = invoice_service._draft  # noqa: SLF001
    assert view._open_customer_mail_outlook(  # noqa: SLF001
        "customer-20844@example.test",
        view._customer_mail_subject(summary),
    )

    assert opened == [
        {
            "to": "customer-20844@example.test",
            "subject": "Wix-Order-Nr. 20844 | sevDesk-Rechnungsnr. RE-DRAFT",
            "sender": "office@xeisworks.at",
        }
    ]


def test_customer_mail_subject_contains_wix_order_and_sevdesk_invoice_numbers(qtbot: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    subject = view._customer_mail_subject(invoice_service._draft)  # noqa: SLF001

    assert subject == "Wix-Order-Nr. 20844 | sevDesk-Rechnungsnr. RE-DRAFT"


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


def test_customs_row_action_opens_customs_only_dialog(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    called: list[str] = []

    monkeypatch.setattr(
        view,
        "_open_customs_declaration_dialog",
        lambda summary: called.append(summary.id),
    )

    view._run_row_action(invoice_service._draft, "customs")  # noqa: SLF001

    assert called == ["draft-1"]


def test_customs_action_passes_selected_order_to_customs_only_dialog(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    created: list[dict[str, object]] = []

    class CustomsDialogStub:
        def __init__(self, *args: object, **kwargs: object) -> None:
            created.append({"args": args, **kwargs})

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.queue_archived_plc_customs",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Kein Archivnachdruck")),
    )
    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.PlcLabelPrintDialog", CustomsDialogStub)

    view._open_customs_declaration_dialog(summary)  # noqa: SLF001

    assert len(created) == 1
    assert created[0]["args"][:3] == (container, summary, view)
    assert created[0]["customs_only"] is True


def test_archived_packing_lists_appear_in_view_and_print_menus(
    qtbot: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    archive = PlcLabelArchive(tmp_path)
    packlists_dir = tmp_path / "packlists"
    packlists_dir.mkdir()
    packlist = packlists_dir / "20844 - RE-DRAFT - Packlisten - 20261013_090000.pdf"
    packlist.write_bytes(b"%PDF-1.7\npacking list")
    archive.refresh_index()
    view._plc_label_archive = archive  # noqa: SLF001
    view._plc_archive_index_ready = True  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    lookup_started = Event()
    lookup_release = Event()

    def find_packing_lists(**_kwargs: object) -> list[Path]:
        lookup_started.set()
        assert lookup_release.wait(2)
        return [packlist]

    monkeypatch.setattr(archive, "find_packing_lists_for_invoice", find_packing_lists)
    view._table.select_source_row(0)  # noqa: SLF001
    view._update_plc_controls()  # noqa: SLF001
    queued: list[tuple[object, str, str]] = []
    started = Event()
    release = Event()
    heartbeat: list[bool] = []

    def queue_print(passed_container: object, path: str, reference: str) -> str:
        started.set()
        assert release.wait(2)
        queued.append((passed_container, path, reference))
        return "packing-job-1"

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.queue_packing_lists",
        queue_print,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)

    ui_heartbeat: list[bool] = []
    timer = QTimer(view)
    timer.timeout.connect(lambda: ui_heartbeat.append(True))
    timer.start(5)
    qtbot.waitUntil(lookup_started.is_set)  # type: ignore[attr-defined]
    qtbot.waitUntil(lambda: bool(ui_heartbeat))  # type: ignore[attr-defined]
    assert not view._view_packing_lists_menu.isEnabled()  # noqa: SLF001
    lookup_release.set()
    qtbot.waitUntil(lambda: view._view_packing_lists_menu.isEnabled())  # type: ignore[attr-defined]  # noqa: SLF001
    timer.stop()

    view._populate_packing_list_menus()  # noqa: SLF001

    assert view._view_packing_lists_menu.isEnabled()  # noqa: SLF001
    assert view._print_packing_lists_menu.isEnabled()  # noqa: SLF001
    assert view._view_packing_lists_menu.actions()[0].text().startswith("Packliste 1 – erstellt ")  # noqa: SLF001
    assert view._print_packing_lists_menu.actions()[0].text().startswith("Packliste 1 – erstellt ")  # noqa: SLF001

    view._print_packing_lists_menu.actions()[0].trigger()  # noqa: SLF001
    qtbot.waitUntil(started.is_set)  # type: ignore[attr-defined]
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    qtbot.waitUntil(lambda: bool(heartbeat))  # type: ignore[attr-defined]
    assert not queued
    view._reprint_archived_packing_list(str(packlist), "20844")  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: view._archived_packing_list_worker is None)  # type: ignore[attr-defined]  # noqa: SLF001
    assert queued == [(container, str(packlist), "20844")]


def test_packing_list_menu_timestamp_does_not_stat_archive_file(monkeypatch: object) -> None:
    def unexpected_stat(_path: Path, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Packlisten-Menue darf keine Datei-Metadaten lesen")

    monkeypatch.setattr(Path, "stat", unexpected_stat)

    label = RechnungenView._packing_list_menu_label(  # noqa: SLF001
        "C:/archive/20844 - RE-1 - Packlisten - 20261013_090000.pdf",
        1,
    )

    assert label.endswith("erstellt 13.10.2026 09:00")


def test_multi_shipment_button_opens_all_labels_and_packing_lists(
    qtbot: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    archive = PlcLabelArchive(tmp_path)
    first = tmp_path / "20844 - RE-DRAFT.pdf"
    second = tmp_path / "20844-2 - RE-DRAFT-2.pdf"
    first.write_bytes(b"%PDF-1.7\nfirst")
    packlists = tmp_path / "packlists"
    packlists.mkdir()
    packing_list = packlists / "20844 - RE-DRAFT - Packlisten - 20261013_090000.pdf"
    packing_list.write_bytes(b"%PDF-1.7\npacking list")
    archive.refresh_index()
    view._plc_label_archive = archive  # noqa: SLF001
    view._plc_archive_index_ready = True  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    view._update_plc_controls()  # noqa: SLF001

    qtbot.waitUntil(
        lambda: ("20844", "RE-DRAFT") in view._plc_archive_lookup_cache,  # noqa: SLF001
        timeout=2000,
    )

    assert view._btn_multi_shipments.isHidden()  # noqa: SLF001

    second.write_bytes(b"%PDF-1.7\nsecond")
    archive.refresh_index()
    view._plc_archive_lookup_cache.clear()  # noqa: SLF001
    view._update_plc_controls()  # noqa: SLF001
    qtbot.waitUntil(lambda: not view._btn_multi_shipments.isHidden(), timeout=2000)  # type: ignore[attr-defined]  # noqa: SLF001

    assert not view._btn_multi_shipments.isHidden()  # noqa: SLF001
    view._populate_multi_shipment_menu()  # noqa: SLF001
    label_menu, packing_menu = [action.menu() for action in view._multi_shipment_menu.actions()]  # noqa: SLF001
    assert [action.text() for action in label_menu.actions()] == [
        "PLC-Label 1 – 20844 / RE-DRAFT",
        "PLC-Label 2 – 20844-2 / RE-DRAFT-2",
    ]
    assert len(packing_menu.actions()) == 1

    opened: list[str] = []
    monkeypatch.setattr(view, "_open_archived_plc_label", lambda path: opened.append(path))
    monkeypatch.setattr(view, "_open_archived_packing_list", lambda path: opened.append(path))
    for action in (*label_menu.actions(), *packing_menu.actions()):
        action.trigger()

    assert opened == [str(first), str(second), str(packing_list)]


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
    monkeypatch.setattr("xw_office.ui.modules.rechnungen.tagesgeschaeft_view._StartDialog.exec", fake_exec)

    view._start_include_product_print = False  # noqa: SLF001
    view._on_start_preflight_ready(preflight)  # noqa: SLF001

    assert called == {"product_check": 1, "dialog": 0}


def test_plain_start_checks_stock_in_preflight(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    container = _build_container(start_stock_booking_enabled=True)
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    invoice_service = container.resolve(InvoiceProcessingService)
    credit_service = container.resolve(B2bCreditService)
    summary = InvoiceSummary(id="stock-preflight", status_code=100)
    monkeypatch.setattr(invoice_service, "load_invoice_summaries", lambda **_kw: [summary])
    monkeypatch.setattr(invoice_service, "filter_start_ready", lambda rows: rows)
    monkeypatch.setattr(invoice_service, "load_buyer_note_cases", lambda _rows: [])
    monkeypatch.setattr(
        invoice_service,
        "build_invoice_inventory_requirements",
        lambda **_kw: {summary.id: {"XW-STOCK": 2}},
    )
    monkeypatch.setattr(credit_service, "evaluate", lambda _rows: [])
    results: list[StartPreflight] = []
    monkeypatch.setattr(view, "_on_start_preflight_ready", results.append)

    view._on_start_clicked(include_product_print=False)  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(results), timeout=3000)

    assert results[0].invoice_requirements == {summary.id: {"XW-STOCK": 2}}
    assert results[0].decisions[0].will_print is True


def test_plain_start_ignores_stock_when_booking_switch_is_off(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    container = _build_container()
    view = TagesgeschaeftView(container)
    qtbot.addWidget(view)
    invoice_service = container.resolve(InvoiceProcessingService)
    credit_service = container.resolve(B2bCreditService)
    summary = InvoiceSummary(id="stock-disabled", status_code=100)
    monkeypatch.setattr(invoice_service, "load_invoice_summaries", lambda **_kw: [summary])
    monkeypatch.setattr(invoice_service, "filter_start_ready", lambda rows: rows)
    monkeypatch.setattr(invoice_service, "load_buyer_note_cases", lambda _rows: [])
    monkeypatch.setattr(
        invoice_service,
        "build_invoice_inventory_requirements",
        lambda **_kw: (_ for _ in ()).throw(AssertionError("stock preflight ran")),
    )
    monkeypatch.setattr(credit_service, "evaluate", lambda _rows: [])
    results: list[StartPreflight] = []
    monkeypatch.setattr(view, "_on_start_preflight_ready", results.append)

    view._on_start_clicked(include_product_print=False)  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(results), timeout=3000)

    assert results[0].decisions == []
    assert results[0].invoice_requirements == {}
    assert results[0].missing_position_data is True


def test_plain_start_stops_before_invoice_release_for_missing_stock(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    view = TagesgeschaeftView(_build_container(start_stock_booking_enabled=True))
    qtbot.addWidget(view)
    warnings: list[str] = []
    continued: list[bool] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    monkeypatch.setattr(view, "_start_missing_product_check", lambda: continued.append(True))
    preflight = StartPreflight(
        open_invoice_count=1,
        decisions=[StartDecision("XW-STOCK", 2, 0, 2, 2, True)],
        missing_position_data=False,
    )

    view._on_start_preflight_ready(preflight)  # noqa: SLF001

    assert not continued
    assert len(warnings) == 1
    assert "XW-STOCK" in warnings[0]
    assert "PRINT-PRODUKTE" in warnings[0]
    assert view._btn_start.isEnabled()  # noqa: SLF001


def test_rechnungen_toolbar_controls_exist(qtbot: object) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    assert view._btn_more.text() == "Weitere Rechnungen laden"  # noqa: SLF001
    assert view._btn_draft.text() == "Rechnungs-Entwurf"  # noqa: SLF001
    assert view._btn_shipping.text() == "VERSAND"  # noqa: SLF001
    assert view._btn_custom_label.text() == "CUSTOM-LABEL"  # noqa: SLF001
    assert view._btn_manual_plc_label.text() == "PLC-LABEL"  # noqa: SLF001
    assert view._btn_plc_statistics.text() == "PLC-ÜBERSICHT"  # noqa: SLF001
    assert view._btn_print.text() == "Drucken"  # noqa: SLF001
    assert view._btn_view.text() == "Ansehen"  # noqa: SLF001
    assert view._btn_open_sevdesk_invoice.text() == "In sevDesk oeffnen"  # noqa: SLF001
    assert [action.text() for action in view._print_menu.actions() if not action.isSeparator()] == [  # noqa: SLF001
        "Rechnung",
        "Versandlabel",
        "PLC-Label",
        "Archivierte Packlisten",
        "Noten / Produkte",
    ]
    assert [action.text() for action in view._view_menu.actions()] == [  # noqa: SLF001
        "Rechnungs-PDF",
        "PLC-Label",
        "Zolldokument",
        "Archivierte Packlisten",
        "Paketinhalt & Tracking",
    ]
    assert not view._btn_print.icon().isNull()  # noqa: SLF001
    assert not view._btn_view.icon().isNull()  # noqa: SLF001
    assert not view._btn_open_sevdesk_invoice.icon().isNull()  # noqa: SLF001
    actions_layout = view._gb_actions.layout()  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_print)) == (0, 0, 1, 1)  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_view)) == (0, 1, 1, 1)  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_open_sevdesk_invoice)) == (0, 2, 1, 1)  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_open_wix_order)) == (1, 0, 1, 1)  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_customer_mail)) == (1, 1, 1, 1)  # noqa: SLF001
    assert actions_layout.getItemPosition(actions_layout.indexOf(view._btn_send_invoice)) == (1, 2, 1, 1)  # noqa: SLF001
    assert view._btn_open_wix_order.text().strip() == "WIX ORDER"  # noqa: SLF001
    assert view._btn_customer_mail.text() == "✉️ Kundenmail"  # noqa: SLF001
    assert view._btn_send_invoice.text() == "Rechnung senden"  # noqa: SLF001
    assert view._shipping_editor is not None  # noqa: SLF001
    assert view._shipping_status.isHidden()  # noqa: SLF001
    assert view._shipping_editor.height() == 28 + (5 * view._shipping_editor.fontMetrics().lineSpacing())  # noqa: SLF001
    view._set_shipping_editor_lines(["Zeile 1", "Zeile 2", "Zeile 3", "Zeile 4", "Zeile 5"])  # noqa: SLF001
    assert view._shipping_editor.blockCount() == 5  # noqa: SLF001
    assert view._shipping_editor.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff  # noqa: SLF001
    assert not view._gb_info.isChecked()  # noqa: SLF001
    assert view._info_content.isHidden()  # noqa: SLF001

    assert view._gb_actions.isHidden()  # noqa: SLF001
    assert not view._btn_print.isEnabled()  # noqa: SLF001
    assert not view._btn_view.isEnabled()  # noqa: SLF001
    assert not view._btn_open_sevdesk_invoice.isEnabled()  # noqa: SLF001
    assert not view._print_invoice_action.isEnabled()  # noqa: SLF001
    assert not view._view_invoice_action.isEnabled()  # noqa: SLF001
    assert not view._btn_open_wix_order.isEnabled()  # noqa: SLF001
    assert not view._btn_customer_mail.isEnabled()  # noqa: SLF001
    assert not view._btn_send_invoice.isEnabled()  # noqa: SLF001


def test_detail_info_is_collapsed_by_default_and_expands_on_click(qtbot: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001

    assert not view._gb_info.isHidden()  # noqa: SLF001
    assert not view._gb_info.isChecked()  # noqa: SLF001
    assert view._info_content.isHidden()  # noqa: SLF001


    view._gb_info.setChecked(True)  # noqa: SLF001

    assert not view._info_content.isHidden()  # noqa: SLF001


def test_invoice_detail_hides_run_tabs_and_close_restores_overview(qtbot: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001

    view._table.select_source_row(0)  # noqa: SLF001

    assert view._print_products_tabs.isHidden()  # noqa: SLF001
    assert not view._detail_invoice_header.isHidden()  # noqa: SLF001
    assert view._btn_close_detail.toolTip().startswith("Rechnungsinfos schließen")  # noqa: SLF001

    view._btn_close_detail.click()  # noqa: SLF001

    assert view._table.selected_source_row() is None  # noqa: SLF001
    assert not view._print_products_tabs.isHidden()  # noqa: SLF001
    assert view._detail_invoice_header.isHidden()  # noqa: SLF001
    assert view._gb_info.isHidden()  # noqa: SLF001


def test_selected_invoice_opens_its_sevdesk_deep_link(qtbot: object, monkeypatch: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    object.__setattr__(container.config.sevdesk, "base_url", "https://tenant.example/api/v1")
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    opened: list[str] = []

    def open_url(url: object) -> bool:
        opened.append(url.toString())
        return True

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.QDesktopServices.openUrl", open_url)

    view._on_open_sevdesk_invoice_clicked()  # noqa: SLF001

    assert opened == ["https://tenant.example/fi/detail/type/RE/id/draft-1"]
    assert view._btn_open_sevdesk_invoice.text() == "Rechnung bearbeiten"  # noqa: SLF001


def test_invoice_send_requires_confirmation(qtbot: object, monkeypatch: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    prompts: list[tuple[str, str]] = []

    def decline(_parent: object, title: str, text: str, *_args: object) -> QMessageBox.StandardButton:
        prompts.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", decline)

    view._on_send_invoice_clicked()  # noqa: SLF001

    assert prompts == [
        (
            "Rechnung senden",
            "Rechnung RE-DRAFT wirklich an den Kunden senden?\n\nDer Versand wird danach sofort gestartet.",
        )
    ]
    assert view._invoice_mail_worker is None  # noqa: SLF001


def test_invoice_pdf_preview_opens_local_pdf_without_printing(qtbot: object, monkeypatch: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    opened: list[str] = []

    def open_url(url: object) -> bool:
        opened.append(url.toLocalFile())
        return True

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view.QDesktopServices.openUrl", open_url)

    view._on_open_invoice_pdf_clicked()  # noqa: SLF001
    qtbot.waitUntil(lambda: view._invoice_pdf_preview_worker is None, timeout=3000)  # noqa: SLF001

    assert len(opened) == 1
    assert opened[0].endswith("draft-1.pdf")
    assert Path(opened[0]).is_file()


def test_detail_buttons_use_same_row_actions_as_invoice_list(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = invoice_service._draft  # noqa: SLF001
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    monkeypatch.setattr(
        invoice_service,
        "get_cached_invoice_work_context",
        lambda _summary: types.SimpleNamespace(confirmed_wix_order_number="20899"),
        raising=False,
    )
    view._update_plc_controls()  # noqa: SLF001
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        view,
        "_run_row_action",
        lambda selected, action: calls.append((selected.id, action)),
    )

    view._on_print_plc_selected()  # noqa: SLF001
    view._btn_open_wix_order.click()  # noqa: SLF001
    view._btn_customer_mail.click()  # noqa: SLF001

    assert calls == [
        (summary.id, "post"),
        (summary.id, "wix"),
        (summary.id, "mail"),
    ]


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


def test_rechnungen_selection_never_fetches_live_sevdesk_details(qtbot: object, monkeypatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "cache-only-select-1",
            "invoiceNumber": "RE-CACHE",
            "status": 200,
            "contact_name": "Cache Kunde",
            "order_reference": "",
        }
    )
    live_calls: list[str] = []

    monkeypatch.setattr(invoice_service, "get_cached_invoice_detail_context", lambda _summary: None)

    def fail_on_live_fetch(next_summary: InvoiceSummary) -> dict[str, object]:
        live_calls.append(str(next_summary.id))
        raise AssertionError("row selection must not fetch live sevDesk details")

    monkeypatch.setattr(invoice_service, "get_invoice_detail_context", fail_on_live_fetch)
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    qtbot.wait(100)

    assert view._dl_number.text() == "RE-CACHE"  # noqa: SLF001
    assert live_calls == []


def test_rechnungen_defers_and_deduplicates_detail_hydration_during_start(
    qtbot: object,
    monkeypatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "start-select-1",
            "invoiceNumber": "RE-START",
            "status": 200,
            "contact_name": "START Kunde",
            "order_reference": "20902",
        }
    )
    hydrate_calls: list[str] = []

    def fake_hydrate(next_summary: InvoiceSummary, _seq: int) -> None:
        hydrate_calls.append(str(next_summary.id))

    monkeypatch.setattr(view, "_hydrate_detail_for_selection", fake_hydrate)
    view.set_start_workflow_running(True)
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    view._refresh_detail_for_selection()  # noqa: SLF001

    assert view._dl_number.text() == "RE-START"  # noqa: SLF001
    assert "nach START" in view._shipping_status.text()  # noqa: SLF001
    assert hydrate_calls == []

    view.set_start_workflow_running(False)
    qtbot.waitUntil(lambda: hydrate_calls == ["start-select-1"], timeout=1000)


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


def test_ready_print_product_reaches_settings_via_right_click(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._open_print_product_ready = lambda _item: True  # type: ignore[method-assign]  # noqa: SLF001
    opened: list[str] = []
    monkeypatch.setattr(  # type: ignore[attr-defined]
        view,
        "_on_open_product_manage_clicked",
        lambda item: opened.append(str(item.sku)),
    )

    row = view._build_open_print_product_row(  # noqa: SLF001
        PrintProductAggregate(sku="XW-6612", title="Geplantes Produkt", description="Besetzung A", quantity=1)
    )
    qtbot.addWidget(row)  # type: ignore[attr-defined]
    buttons = row.findChildren(QToolButton)
    assert len(buttons) == 1
    button = buttons[0]

    assert button.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert "Rechtsklick" in button.toolTip()
    button.customContextMenuRequested.emit(QPoint(0, 0))

    assert opened == ["XW-6612"]


def test_open_product_inventory_is_informational_and_never_disables_action(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    item = PrintProductAggregate(
        sku="XW-STOCK-INFO",
        title="Bestandsprodukt",
        description="Besetzung A",
        quantity=2,
    )
    block = PieceBlock(
        sku=item.sku,
        name=item.title,
        qty_needed=item.quantity,
        product=Product(
            id="stock-info",
            sku=item.sku,
            name=item.title,
            article_kind="pod",
        ),
        stock_status=StockStatus(
            sku=item.sku,
            product_name=item.title,
            is_digital=False,
            on_hand=10,
            min_stock_target=5,
            reprint_batch_qty=3,
        ),
    )
    assert block.print_qty == 0
    monkeypatch.setattr(view, "_piece_block_from_open_product", lambda _item: block)
    monkeypatch.setattr(view, "_open_print_product_ready", lambda _item: True)

    # Even before printer discovery completes, the button stays interactive so
    # its right-click settings path remains available.
    view._print_allowed = False  # noqa: SLF001
    row = view._build_open_print_product_row(item)  # noqa: SLF001
    qtbot.addWidget(row)  # type: ignore[attr-defined]
    button = row.findChildren(QToolButton)[0]

    assert button.isEnabled()
    assert button.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


def test_open_product_print_uses_visible_quantity_not_inventory_suggestion(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._print_allowed = True  # noqa: SLF001
    item = PrintProductAggregate(
        sku="XW-STOCK-PRINT",
        title="Bestandsprodukt",
        description="Besetzung A",
        quantity=2,
    )
    block = PieceBlock(
        sku=item.sku,
        name=item.title,
        qty_needed=item.quantity,
        product=Product(
            id="stock-print",
            sku=item.sku,
            name=item.title,
            article_kind="pod",
        ),
        stock_status=StockStatus(
            sku=item.sku,
            product_name=item.title,
            is_digital=False,
            on_hand=10,
            min_stock_target=5,
            reprint_batch_qty=3,
        ),
    )
    printed: list[tuple[str, int]] = []
    monkeypatch.setattr(view, "_piece_block_from_open_product", lambda _item: block)
    monkeypatch.setattr(
        view,
        "_on_product_print_clicked",
        lambda current, quantity, **_kwargs: printed.append((current.sku, quantity)),
    )

    view._on_open_product_print_clicked(item)  # noqa: SLF001

    assert block.print_qty == 0
    assert printed == [(item.sku, 2)]


def test_open_product_stock_plan_keeps_order_quantity_printable(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    item = PrintProductAggregate(
        sku="XW-STOCK-PLAN",
        title="Bestandsprodukt",
        description="Besetzung A",
        quantity=2,
    )
    block = PieceBlock(
        sku=item.sku,
        name=item.title,
        qty_needed=item.quantity,
        product=Product(
            id="stock-plan",
            sku=item.sku,
            name=item.title,
            article_kind="pod",
        ),
        stock_status=StockStatus(
            sku=item.sku,
            product_name=item.title,
            is_digital=False,
            on_hand=10,
            min_stock_target=5,
            reprint_batch_qty=3,
        ),
    )
    monkeypatch.setattr(view, "_piece_block_from_open_product", lambda _item: block)

    planned = view._plan_open_print_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="stock-is-informational",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[item],
        )
    ).print_products[0]

    assert planned.quantity == 2
    assert planned.ordered_quantity == 2
    assert planned.on_hand == 10
    assert planned.print_quantity == 0


def test_open_product_enrichment_resolves_hub_variants_as_one_batch(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    import uuid
    from xw_office.services.product_hub.inventory import InventoryV2Service

    container, _invoice_service = _build_rechnungen_test_container()
    items = [
        PrintProductAggregate(sku=f"XW-BATCH-{index}", title=f"Produkt {index}", description="", quantity=1)
        for index in range(2)
    ]
    variant_ids = [uuid.uuid4(), uuid.uuid4()]
    resolution_calls: list[list[str]] = []
    stock_calls: list[list[uuid.UUID]] = []
    catalog_calls: list[list[str]] = []

    class FakeCatalog:
        def warm_hub_products(self, skus: list[str]) -> None:
            catalog_calls.append(skus)

        def clear_warmed_hub_products(self) -> None:
            return None

    container.register(ProductCatalogService, lambda _: FakeCatalog())  # type: ignore[arg-type,return-value]

    class FakeHub:
        def resolve_variants_by_skus(self, skus: list[str]) -> dict[str, object]:
            resolution_calls.append(skus)
            return {
                item.sku: types.SimpleNamespace(variant=types.SimpleNamespace(id=variant_id))
                for item, variant_id in zip(items, variant_ids, strict=True)
            }

        def variant_on_hand_many(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
            stock_calls.append(ids)
            return {variant_id: 8 + index for index, variant_id in enumerate(variant_ids)}

    container.register(InventoryV2Service, lambda _: FakeHub())  # type: ignore[arg-type,return-value]
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.resolve_piece_print_config",
        lambda _catalog, block: types.SimpleNamespace(
            **{
                **block.__dict__,
                "product": Product(id=block.sku, sku=block.sku, name=block.name),
            }
        ),
    )

    result = view._resolve_piece_blocks_from_open_products(items)  # noqa: SLF001

    assert [call for call in catalog_calls if call] == [[item.sku for item in items]]
    assert resolution_calls == [[item.sku for item in items]]
    assert stock_calls == [variant_ids]
    assert [result[view._open_product_check_key(item)].stock_status.on_hand for item in items] == [8, 9]  # noqa: SLF001


def test_print_products_remain_frozen_after_completed_run(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    first = PrintProductAggregate(
        sku="XW-FIRST",
        title="Erstes Produkt",
        description="Besetzung A",
        quantity=2,
    )
    second = PrintProductAggregate(
        sku="XW-SECOND",
        title="Zweites Produkt",
        description="Besetzung B",
        quantity=1,
    )

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="run-1",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[first],
        )
    )
    view.mark_print_products_last_run()
    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="empty",
            total=0,
            with_ref=0,
            physical=0,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
        )
    )

    assert view._gb_open_products.title() == "PRINT PRODUKTE (last run)"  # noqa: SLF001
    assert "Erstes Produkt" in view._open_products_text.toPlainText()  # noqa: SLF001

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="run-2",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[second],
        )
    )

    text = view._open_products_text.toPlainText()  # noqa: SLF001
    assert "Erstes Produkt" in text
    assert "Zweites Produkt" not in text


def test_print_product_description_is_compact_and_omits_unreleased_title_echo() -> None:
    regular = PrintProductAggregate(
        sku="XW-501.03-P",
        title="Christkindl-Hits",
        description="Besetzung: MH-ZST physisch GESAMT",
        quantity=1,
    )
    unreleased = PrintProductAggregate(
        sku="XW-010",
        title="In deinen Augen",
        description=(
            "Name des Stückes / der Stücke: Freunde, ja heute feiern wir | "
            "Sonstige Bemerkungen: 2Flh, Btp, Tuba C"
        ),
        quantity=1,
    )

    assert RechnungenView._open_product_description(regular) == "MH-ZST physisch GESAMT"  # noqa: SLF001
    assert RechnungenView._open_product_description(unreleased) == "2Flh, Btp, Tuba C"  # noqa: SLF001
    assert RechnungenView._open_product_description(  # noqa: SLF001
        PrintProductAggregate(
            sku="XW-010",
            title="Freunde, ja heute feiern wir",
            description="Name des Stückes / der Stücke: Freunde, ja heute feiern wir",
            quantity=1,
        )
    ) == ""


def test_analysis_panel_and_load_more_button_have_usable_width(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    assert view._detail_scroll.minimumWidth() == 390  # noqa: SLF001
    assert view._detail_scroll.maximumWidth() == 520  # noqa: SLF001
    assert view._main_splitter.handleWidth() == 10  # noqa: SLF001
    assert view._btn_more.minimumWidth() == 230  # noqa: SLF001


def test_last_run_print_and_unreleased_panels_restore_after_restart(qtbot: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    product = PrintProductAggregate(
        sku="XW-010",
        title="Unreleased-Produkt",
        description="",
        quantity=1,
    )
    assignment = UnreleasedAssignment(
        title="Marsch für Anna",
        shipping_name="Anna Versand",
        order_reference="20910",
    )
    buyer_note = BuyerNote(
        customer_name="Anna Versand",
        note="Bitte sauber verpacken.",
        order_reference="20910",
    )
    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="run-persist",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[product],
            buyer_notes=[buyer_note],
            unreleased_assignments=[assignment],
        )
    )

    view.mark_print_products_last_run(
        invoice_print_ids=["invoice-1"],
        label_print_ids=["invoice-1"],
    )

    qtbot.waitUntil(lambda: bool(invoice_service.last_start_overview.get("saved_at")))
    assert invoice_service.last_start_overview["saved_at"]
    persisted_run = invoice_service.last_start_overview["runs"][0]
    assert persisted_run["invoice_print_ids"] == ["invoice-1"]
    assert persisted_run["label_print_ids"] == ["invoice-1"]
    restarted = RechnungenView(container)
    qtbot.addWidget(restarted)
    restarted._restore_last_start_overview()  # noqa: SLF001
    qtbot.waitUntil(lambda: bool(restarted._print_run_history))  # noqa: SLF001

    assert restarted._active_run_output_ids(labels=False) == ["invoice-1"]  # noqa: SLF001
    assert restarted._active_run_output_ids(labels=True) == ["invoice-1"]  # noqa: SLF001

    assert restarted._gb_open_products.title() == "PRINT PRODUKTE (last run)"  # noqa: SLF001
    assert restarted._gb_buyer_notes.title() == "KÄUFER-NOTIZEN (last run)"  # noqa: SLF001
    assert restarted._gb_unreleased.title() == "UNRELEASED (last run)"  # noqa: SLF001
    assert "Unreleased-Produkt" in restarted._open_products_text.toPlainText()  # noqa: SLF001
    assert "Bitte sauber verpacken." in restarted._buyer_notes_text.toPlainText()  # noqa: SLF001
    assert "Marsch für Anna -> Anna Versand [20910]" in restarted._unreleased_text.toPlainText()  # noqa: SLF001


def test_start_history_settings_write_runs_off_ui_thread_and_keeps_latest_run(
    qtbot: object,
    monkeypatch: MonkeyPatch,
) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_restore_last_start_overview", lambda *_args: None)
    main_thread_id = get_ident()
    first_entered, release_first, heartbeat = Event(), Event(), Event()
    written: list[dict[str, object]] = []

    def write(payload: dict[str, object]) -> None:
        assert get_ident() != main_thread_id
        written.append(dict(payload))
        if len(written) == 1:
            first_entered.set()
            assert release_first.wait(3)
        invoice_service.last_start_overview = dict(payload)

    monkeypatch.setattr(invoice_service, "write_last_start_overview", write)
    timer = QTimer(view)
    timer.setInterval(5)
    timer.timeout.connect(heartbeat.set)
    timer.start()
    try:
        view.mark_print_products_last_run(invoice_print_ids=["first-run"])
        qtbot.waitUntil(first_entered.is_set, timeout=2000)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        view.mark_print_products_last_run(invoice_print_ids=["second-run"])
        assert invoice_service.last_start_overview == {}
        assert view.prepare_shutdown() is False
        assert view.shutdown_complete() is False
    finally:
        release_first.set()
        timer.stop()

    qtbot.waitUntil(
        lambda: view._print_history_worker is None  # noqa: SLF001
        and invoice_service.last_start_overview.get("runs", [{}])[0].get("invoice_print_ids")
        == ["second-run"]
        and view.shutdown_complete(),
        timeout=3000,
    )
    assert [payload["runs"][0]["invoice_print_ids"] for payload in written] == [
        ["first-run"],
        ["second-run"],
    ]


def test_start_history_restore_runs_off_ui_thread(qtbot: object, monkeypatch: MonkeyPatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    invoice_service.last_start_overview = {
        "saved_at": "2026-11-12T08:00:00+01:00",
        "runs": [
            {
                "saved_at": "2026-11-12T08:00:00+01:00",
                "print_products": [{"sku": "SKU-1", "title": "Noten", "quantity": 1}],
            }
        ],
    }
    main_thread_id = get_ident()
    entered, release, heartbeat = Event(), Event(), Event()
    original_read = invoice_service.read_last_start_overview

    def read() -> dict[str, object]:
        assert get_ident() != main_thread_id
        entered.set()
        assert release.wait(3)
        return original_read()

    monkeypatch.setattr(invoice_service, "read_last_start_overview", read)
    view = RechnungenView(container)
    qtbot.addWidget(view)
    timer = QTimer(view)
    timer.setInterval(5)
    timer.timeout.connect(heartbeat.set)
    timer.start()
    try:
        view._restore_last_start_overview()  # noqa: SLF001
        qtbot.waitUntil(entered.is_set, timeout=2000)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        assert view._print_run_history == []  # noqa: SLF001
    finally:
        release.set()
        timer.stop()

    qtbot.waitUntil(lambda: bool(view._print_run_history), timeout=3000)  # noqa: SLF001
    assert view._last_run_print_products[0].title == "Noten"  # noqa: SLF001


def test_run_output_buttons_print_all_persisted_targets(qtbot: object, monkeypatch: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    view._print_allowed = True  # noqa: SLF001
    view.mark_print_products_last_run(
        invoice_print_ids=["invoice-1", "invoice-2"],
        label_print_ids=["invoice-1", "invoice-2"],
    )

    assert view._btn_print_run_invoices.isEnabled()  # noqa: SLF001
    assert view._btn_print_run_labels.isEnabled()  # noqa: SLF001
    view._btn_print_run_invoices.click()  # noqa: SLF001
    qtbot.waitUntil(
        lambda: invoice_service.run_print_calls == [(["invoice-1", "invoice-2"], False)]
    )
    qtbot.waitUntil(lambda: view._run_output_worker is None)  # noqa: SLF001

    view._btn_print_run_labels.click()  # noqa: SLF001
    qtbot.waitUntil(
        lambda: invoice_service.run_print_calls
        == [(["invoice-1", "invoice-2"], False), (["invoice-1", "invoice-2"], True)]
    )
    qtbot.waitUntil(lambda: view._run_output_worker is None)  # noqa: SLF001


def test_run_output_labels_queue_while_invoice_print_is_running(qtbot: object, monkeypatch: object) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    invoice_started = Event()
    release_invoice = Event()
    original_print = invoice_service.print_run_documents

    def delayed_print(invoice_ids: list[str], *, labels: bool) -> dict[str, object]:
        if not labels:
            invoice_started.set()
            assert release_invoice.wait(timeout=2)
        return original_print(invoice_ids, labels=labels)

    monkeypatch.setattr(invoice_service, "print_run_documents", delayed_print)
    view._print_allowed = True  # noqa: SLF001
    view.mark_print_products_last_run(
        invoice_print_ids=["invoice-1", "invoice-2"],
        label_print_ids=["invoice-1", "invoice-2"],
    )

    view._btn_print_run_invoices.click()  # noqa: SLF001
    qtbot.waitUntil(invoice_started.is_set)
    assert not view._btn_print_run_invoices.isEnabled()  # noqa: SLF001
    assert view._btn_print_run_labels.isEnabled()  # noqa: SLF001

    view._btn_print_run_labels.click()  # noqa: SLF001
    assert not view._btn_print_run_labels.isEnabled()  # noqa: SLF001
    assert invoice_service.run_print_calls == []

    release_invoice.set()
    qtbot.waitUntil(
        lambda: invoice_service.run_print_calls
        == [(["invoice-1", "invoice-2"], False), (["invoice-1", "invoice-2"], True)]
    )
    qtbot.waitUntil(lambda: view._run_output_worker is None)  # noqa: SLF001


def test_unreleased_assignments_are_grouped_by_buyer(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    assignments = [
        UnreleasedAssignment(title="Marsch", shipping_name="Anna Versand", order_reference="20910"),
        UnreleasedAssignment(title="Polka", shipping_name="Anna Versand", order_reference="20911"),
        UnreleasedAssignment(title="Walzer", shipping_name="Bruno Versand", order_reference="20912"),
    ]

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="grouped-unreleased",
            total=3,
            with_ref=3,
            physical=3,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            unreleased_assignments=assignments,
        )
    )

    # Header, one row for Anna, one row for Bruno, then the layout stretch.
    assert view._unreleased_rows_layout.count() == 4  # noqa: SLF001
    assert view._unreleased_text.toPlainText().count("Anna Versand") == 2  # noqa: SLF001


def test_print_all_products_button_prints_displayed_quantities(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    products = [
        PrintProductAggregate(sku="XW-FIRST", title="Erstes Produkt", description="Besetzung A", quantity=2),
        PrintProductAggregate(sku="XW-SECOND", title="Zweites Produkt", description="Besetzung B", quantity=3),
    ]
    prepared: list[tuple[str, int, bool]] = []
    printed: list[tuple[str, int]] = []

    view._open_print_product_ready = lambda _item: True  # type: ignore[method-assign]  # noqa: SLF001

    def fake_piece(item: PrintProductAggregate) -> PieceBlock:
        return PieceBlock(sku=str(item.sku), name=str(item.title), qty_needed=int(item.quantity))

    def fake_prepare(_parent: object, _container: object, *, piece: PieceBlock, copies: int, wait: bool = False):
        prepared.append((piece.sku, copies, wait))

        def job() -> None:
            printed.append((piece.sku, copies))

        return job

    monkeypatch.setattr(view, "_piece_block_from_open_product", fake_piece)
    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print", fake_prepare)

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="print-all",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=products,
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    assert view._btn_print_all_products.isEnabled()  # noqa: SLF001

    view._on_print_all_open_products_clicked()  # noqa: SLF001

    qtbot.waitUntil(lambda: view._product_print_worker is None, timeout=2000)  # noqa: SLF001
    assert prepared == [("XW-FIRST", 2, True), ("XW-SECOND", 3, True)]
    assert printed == [("XW-FIRST", 2), ("XW-SECOND", 3)]
    assert view._last_print_all_products_key is not None  # noqa: SLF001


def test_print_all_products_uses_adjusted_open_quantities(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    product = PrintProductAggregate(sku="XW-FIRST", title="Erstes Produkt", description="A", quantity=2)
    printed: list[str] = []

    view._open_print_product_ready = lambda _item: True  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(
        view,
        "_piece_block_from_open_product",
        lambda item: PieceBlock(sku=str(item.sku), name=str(item.title), qty_needed=int(item.quantity)),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print",
        lambda _parent, _container, *, piece, copies, wait=False: (
            lambda: printed.append(f"{piece.sku}:{copies}:{wait}")
        ),
    )

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="print-all-adjusted",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[product],
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    spinboxes = view._gb_open_products.findChildren(QSpinBox)  # noqa: SLF001
    assert len(spinboxes) == 1
    assert spinboxes[0].value() == 2
    spinboxes[0].setValue(5)

    view._on_print_all_open_products_clicked()  # noqa: SLF001
    qtbot.waitUntil(lambda: view._product_print_worker is None, timeout=2000)  # noqa: SLF001

    assert printed == ["XW-FIRST:5:True"]


def test_open_product_quantity_correction_keeps_later_discoveries(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    initial = PrintProductAggregate(
        sku="XW-GROWING",
        title="Wachsendes Produkt",
        description="A",
        quantity=5,
    )

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="growing-1",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=1,
            with_note=0,
            plc=0,
            complete=False,
            print_products=[initial],
        )
    )
    view._on_printer_status(True)  # noqa: SLF001
    spinbox = view._gb_open_products.findChildren(QSpinBox)[0]  # noqa: SLF001

    spinbox.setValue(3)

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="growing-2",
            total=2,
            with_ref=2,
            physical=2,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[
                PrintProductAggregate(
                    sku="XW-GROWING",
                    title="Wachsendes Produkt",
                    description="A",
                    quantity=7,
                )
            ],
        )
    )

    # The previous row is pending Qt's deleteLater(); the last child belongs
    # to the freshly rendered cumulative overview.
    updated_spinbox = view._gb_open_products.findChildren(QSpinBox)[-1]  # noqa: SLF001
    assert updated_spinbox.minimum() == 0
    assert updated_spinbox.value() == 5
    assert view._selected_displayed_print_products()[0].quantity == 5  # noqa: SLF001


def test_open_product_quantity_zero_removes_product_from_print_selection(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="zero-quantity",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[
                PrintProductAggregate(
                    sku="XW-ZERO",
                    title="Erledigtes Produkt",
                    description="A",
                    quantity=2,
                )
            ],
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    spinbox = view._gb_open_products.findChildren(QSpinBox)[0]  # noqa: SLF001
    spinbox.setValue(0)

    assert view._displayed_print_products()[0].quantity == 0  # noqa: SLF001
    assert view._selected_displayed_print_products() == []  # noqa: SLF001
    assert not view._btn_print_all_products.isEnabled()  # noqa: SLF001
def test_print_selected_products_skips_unchecked_rows(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    products = [
        PrintProductAggregate(sku="XW-FIRST", title="Erstes Produkt", description="A", quantity=2),
        PrintProductAggregate(sku="XW-SECOND", title="Zweites Produkt", description="B", quantity=3),
    ]
    printed: list[str] = []
    view._open_print_product_ready = lambda _item: True  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(
        view,
        "_piece_block_from_open_product",
        lambda item: PieceBlock(sku=str(item.sku), name=str(item.title), qty_needed=int(item.quantity)),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print",
        lambda _parent, _container, *, piece, copies, wait=False: (
            lambda: printed.append(f"{piece.sku}:{copies}:{wait}")
        ),
    )

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="print-selected",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=products,
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    checkboxes = view._gb_open_products.findChildren(QCheckBox)  # noqa: SLF001
    assert view._btn_print_all_products.text() == "PRINT SELECTED PRODUCTS"  # noqa: SLF001
    assert len(checkboxes) == 2
    assert all(checkbox.isChecked() for checkbox in checkboxes)
    checkboxes[1].setChecked(False)

    view._on_print_all_open_products_clicked()  # noqa: SLF001
    qtbot.waitUntil(lambda: view._product_print_worker is None, timeout=2000)  # noqa: SLF001

    assert printed == ["XW-FIRST:2:True"]


def test_individual_product_print_clicks_are_queued_without_blocking_each_other(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    release = Event()
    started: list[str] = []
    accepted: list[str] = []

    def fake_prepare(_parent: object, _container: object, *, piece: PieceBlock, copies: int, wait: bool = False):
        def job() -> None:
            started.append(piece.sku)
            release.wait(timeout=2)

        return job

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print", fake_prepare)
    view._on_printer_status(True)  # noqa: SLF001

    view._on_product_print_clicked(  # noqa: SLF001
        PieceBlock(sku="XW-FIRST", name="Erstes Produkt", qty_needed=1),
        1,
        on_accepted=lambda: accepted.append("XW-FIRST"),
    )
    view._on_product_print_clicked(  # noqa: SLF001
        PieceBlock(sku="XW-SECOND", name="Zweites Produkt", qty_needed=1),
        1,
        on_accepted=lambda: accepted.append("XW-SECOND"),
    )

    assert accepted == ["XW-FIRST", "XW-SECOND"]
    assert len(view._product_print_handles) == 2  # noqa: SLF001
    qtbot.waitUntil(lambda: started == ["XW-FIRST"], timeout=1000)
    release.set()
    qtbot.waitUntil(lambda: not view._product_print_handles, timeout=2000)  # noqa: SLF001
    assert started == ["XW-FIRST", "XW-SECOND"]


def test_individual_product_print_rejects_duplicate_active_sku(
    qtbot: object,
    monkeypatch: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    release = Event()
    prepared: list[str] = []
    accepted: list[str] = []

    def fake_prepare(_parent: object, _container: object, *, piece: PieceBlock, copies: int, wait: bool = False):
        prepared.append(piece.sku)

        def job() -> None:
            release.wait(timeout=2)

        return job

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print", fake_prepare)
    view._on_printer_status(True)  # noqa: SLF001
    view._on_product_print_clicked(  # noqa: SLF001
        PieceBlock(sku="XW-DUP", name="Notenheft", qty_needed=1),
        1,
        on_accepted=lambda: accepted.append("first"),
    )
    qtbot.waitUntil(lambda: bool(view._product_print_handles), timeout=1000)  # noqa: SLF001
    view._on_product_print_clicked(  # noqa: SLF001
        PieceBlock(sku="XW-DUP", name="Notenheft", qty_needed=1),
        1,
        on_accepted=lambda: accepted.append("duplicate"),
    )

    assert prepared == ["XW-DUP"]
    assert accepted == ["first"]
    assert len(view._product_print_handles) == 1  # noqa: SLF001
    release.set()
    qtbot.waitUntil(lambda: not view._product_print_handles, timeout=2000)  # noqa: SLF001
    assert not view._active_individual_print_keys  # noqa: SLF001


def test_product_print_partial_failure_books_completed_copies(qtbot: object, monkeypatch: object) -> None:
    """Regression test for the XW-6612 reorder's failure path.

    When a multi-copy print job fails partway (e.g. printer goes offline),
    the copies confirmed before the failure must still be reported/bookable
    instead of the whole run silently losing that count.
    """
    from xw_office.services.printing.planned_pdf_printer import PrintPlanPartialFailure

    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view._on_printer_status(True)  # noqa: SLF001

    def fake_prepare(_parent: object, _container: object, *, piece: PieceBlock, copies: int, wait: bool = False):
        def job() -> None:
            raise PrintPlanPartialFailure("Drucker offline", completed_copies=2, job_ids=["a", "b"])

        return job

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print", fake_prepare)

    results: list[object] = []
    monkeypatch.setattr(view, "_on_product_print_result", lambda payload: results.append(payload))  # type: ignore[method-assign]

    view._on_product_print_clicked(  # noqa: SLF001
        PieceBlock(sku="XW-6612", name="Testprodukt", qty_needed=5),
        5,
    )

    qtbot.waitUntil(lambda: not view._product_print_handles, timeout=2000)  # noqa: SLF001

    assert results == [
        {
            "sku": "XW-6612",
            "quantity": 2,
            "stock_warning": "kein sevDesk-Part fuer Bestandsbuchung hinterlegt",
            "print_warning": "Drucker offline",
        }
    ]


def test_invoice_product_rows_are_selected_for_batch_print_by_default(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    block = PieceBlock(sku="XW-INVOICE", name="Rechnungsprodukt", qty_needed=2)
    view._piece_model.set_pieces(  # noqa: SLF001
        [
            {
                "block": block,
                "flagged": True,
                "quantity": 2,
                "header": "Rechnungsprodukt",
                "details": [],
                "stock": "",
                "stock_color": "#64748b",
                "print_enabled": True,
            }
        ]
    )

    assert view._piece_model.rows() == [(block, 2, True)]  # noqa: SLF001
    view._piece_model.toggle_selected(0)  # noqa: SLF001
    assert view._piece_model.rows() == [(block, 2, False)]  # noqa: SLF001


def test_selected_invoice_ready_product_right_click_opens_print_settings(
    qtbot: object,
    tmp_path: object,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    view.show()
    pdf_path = tmp_path / "ready.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    block = PieceBlock(
        sku="XW-RIGHT",
        name="Rechnungsprodukt",
        qty_needed=1,
        print_profile_id="noten_a5",
        product=Product(
            id="right-click",
            sku="XW-RIGHT",
            name="Rechnungsprodukt",
            print_file_path=str(pdf_path),
        ),
    )
    view._piece_model.set_pieces(  # noqa: SLF001
        [
            {
                "block": block,
                "flagged": True,
                "quantity": 1,
                "header": "Rechnungsprodukt",
                "details": [],
                "stock": "",
                "stock_color": "#64748b",
                "print_enabled": True,
            }
        ]
    )
    view._gb_stuecke.show()  # noqa: SLF001
    view._piece_list.show()  # noqa: SLF001
    opened: list[str] = []
    printed: list[str] = []
    view._piece_delegate.manage_clicked.disconnect()  # noqa: SLF001
    view._piece_delegate.print_clicked.disconnect()  # noqa: SLF001
    view._piece_delegate.manage_clicked.connect(lambda piece: opened.append(piece.sku))  # noqa: SLF001
    view._piece_delegate.print_clicked.connect(lambda piece, _qty: printed.append(piece.sku))  # noqa: SLF001
    index = view._piece_model.index(0, 0)  # noqa: SLF001
    row_rect = view._piece_list.visualRect(index)  # noqa: SLF001
    action_rect = view._piece_delegate._button_rects(row_rect, has_print_config=True)["print"]  # noqa: SLF001

    qtbot.mouseClick(
        view._piece_list.viewport(),  # noqa: SLF001
        Qt.MouseButton.RightButton,
        pos=action_rect.center(),
    )

    assert opened == ["XW-RIGHT"]
    assert printed == []


def test_invoice_product_row_quantity_can_be_adjusted(qtbot: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    block = PieceBlock(sku="XW-INVOICE", name="Rechnungsprodukt", qty_needed=2)
    view._piece_model.set_pieces(  # noqa: SLF001
        [
            {
                "block": block,
                "flagged": True,
                "quantity": 2,
                "header": "Rechnungsprodukt",
                "details": [],
                "stock": "",
                "stock_color": "#64748b",
                "print_enabled": True,
            }
        ]
    )

    view._piece_model.adjust_quantity(0, 1)  # noqa: SLF001
    assert view._piece_model.rows() == [(block, 3, True)]  # noqa: SLF001
    view._piece_model.adjust_quantity(0, -10)  # noqa: SLF001
    assert view._piece_model.rows() == [(block, 1, True)]  # noqa: SLF001


def test_print_all_products_warns_before_reprint(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    product = PrintProductAggregate(
        sku="XW-FIRST",
        title="Erstes Produkt",
        description="Besetzung A",
        quantity=2,
    )
    print_calls: list[str] = []
    questions: list[str] = []

    view._open_print_product_ready = lambda _item: True  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(
        view,
        "_piece_block_from_open_product",
        lambda item: PieceBlock(sku=str(item.sku), name=str(item.title), qty_needed=int(item.quantity)),
    )

    def fake_prepare(_parent: object, _container: object, *, piece: PieceBlock, copies: int, wait: bool = False):
        def job() -> None:
            print_calls.append(f"{piece.sku}:{copies}:{wait}")

        return job

    def fake_question(*args: object, **_kwargs: object) -> QMessageBox.StandardButton:
        questions.append(str(args[2]))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print", fake_prepare)
    monkeypatch.setattr(QMessageBox, "question", fake_question)

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="print-all-repeat",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=[product],
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    view._on_print_all_open_products_clicked()  # noqa: SLF001
    qtbot.waitUntil(lambda: view._product_print_worker is None, timeout=2000)  # noqa: SLF001
    view._on_print_all_open_products_clicked()  # noqa: SLF001

    assert print_calls == ["XW-FIRST:2:True"]
    assert questions == ["Produkte bereits gedruckt.\n\nErneut drucken?"]


def test_print_all_products_configures_missing_products_in_order(qtbot: object, monkeypatch: object) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    products = [
        PrintProductAggregate(sku="XW-FIRST", title="Erstes Produkt", description="", quantity=1),
        PrintProductAggregate(sku="XW-SECOND", title="Zweites Produkt", description="", quantity=1),
    ]
    configured: list[str] = []

    view._open_print_product_ready = lambda _item: False  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(
        view,
        "_piece_block_from_open_product",
        lambda item: PieceBlock(sku=str(item.sku), name=str(item.title), qty_needed=int(item.quantity)),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog._configure_missing_piece_print",
        lambda _parent, _container, piece: configured.append(piece.sku) or True,
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.print_dialog.prepare_piece_pdf_print",
        lambda *_args, **_kwargs: (lambda: None),
    )

    view._apply_open_invoice_overview(  # noqa: SLF001
        OpenInvoiceOverview(
            key="print-all-missing",
            total=1,
            with_ref=1,
            physical=1,
            digital=0,
            unknown=0,
            with_note=0,
            plc=0,
            complete=True,
            print_products=products,
        )
    )
    view._on_printer_status(True)  # noqa: SLF001

    view._on_print_all_open_products_clicked()  # noqa: SLF001
    qtbot.waitUntil(lambda: view._product_print_worker is None, timeout=2000)  # noqa: SLF001

    assert configured == ["XW-FIRST", "XW-SECOND"]


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
    assert dialog._primary_order_number.text() == "20856"  # noqa: SLF001
    assert not hasattr(dialog, "_recipient_phone")

    dialog._primary_order_number.setText("21104")  # noqa: SLF001
    dialog._secondary_order_number.setText("21105")  # noqa: SLF001

    dialog._on_context_loaded(  # noqa: SLF001
        _PlcDialogContext(
            order_number="20856",
            address_lines=["PLC Customer", "Teststrasse 1", "1030 Wien", "AUSTRIA"],
            weight_kg=4.01,
            items=[],
        )
    )

    assert dialog._primary_order_number.text() == "21104"  # noqa: SLF001
    assert dialog._build_reference() == "21104 + 21105"  # noqa: SLF001
    assert dialog._price_label.text() == "Preis: 7,21 €"  # noqa: SLF001


def test_plc_dialog_defers_wix_loading_until_after_first_event_loop_turn(
    qtbot: object,
    monkeypatch: object,
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(PlcLabelPrintDialog, "_load_context", lambda _self: started.append(True))
    summary = InvoiceSummary.model_validate(
        {
            "id": "plc-lazy",
            "invoiceNumber": "RE-PLC-LAZY",
            "status": 200,
            "contact_name": "PLC Customer",
            "order_reference": "20857",
        }
    )

    dialog = PlcLabelPrintDialog(_build_container(), summary)
    qtbot.addWidget(dialog)

    assert started == []
    assert "Wix-Cache" in dialog._status.text()  # noqa: SLF001
    qtbot.waitUntil(lambda: started == [True], timeout=1000)


def test_manual_plc_dialog_uses_structured_address_and_office_email(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_build_container(), None)
    qtbot.addWidget(dialog)

    dialog._company_edit.setText("XeisWorks")  # noqa: SLF001
    dialog._name_edit.setText("Max Mustermann")  # noqa: SLF001
    dialog._street_edit.setText("Teststraße 1")  # noqa: SLF001
    dialog._postal_city_edit.setText("1030 Wien")  # noqa: SLF001
    dialog._country_combo.setEditText("Österreich")  # noqa: SLF001

    assert dialog._current_address_lines() == [  # noqa: SLF001
        "XeisWorks",
        "Max Mustermann",
        "Teststraße 1",
        "1030 Wien",
        "Austria",
    ]
    assert dialog._recipient_email.text() == "office@xeisworks.at"  # noqa: SLF001
    assert not hasattr(dialog, "_recipient_phone")
    assert "Österreich" in dialog._country_combo.completer().model().stringList()  # noqa: SLF001


def test_manual_plc_dialog_updates_price_from_country_and_weight(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_build_container(), None)
    qtbot.addWidget(dialog)

    dialog._name_edit.setText("Max Mustermann")  # noqa: SLF001
    dialog._street_edit.setText("Teststraße 1")  # noqa: SLF001
    dialog._postal_city_edit.setText("1030 Wien")  # noqa: SLF001
    dialog._country_combo.setEditText("Austria")  # noqa: SLF001
    dialog._weight_edit.setText("2,01")  # noqa: SLF001

    assert dialog._price_label.text() == "Preis: 6,39 €"  # noqa: SLF001

    dialog._weight_edit.setText("8")  # noqa: SLF001

    assert dialog._price_label.text() == "Preis: 7,21 €"  # noqa: SLF001

    dialog._country_combo.setEditText("Switzerland")  # noqa: SLF001
    dialog._weight_edit.setText("4")  # noqa: SLF001

    assert dialog._product_combo.currentData() is None  # noqa: SLF001
    assert dialog._product_combo.currentText() == "Paket Plus Int. Outbound"  # noqa: SLF001
    assert dialog._price_label.text() == "Preis: 19,88 €"  # noqa: SLF001


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


def test_rechnungen_falls_back_to_sevdesk_when_wix_reference_is_not_found(
    qtbot: object,
    monkeypatch: MonkeyPatch,
) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "manual-reference",
            "invoiceNumber": "RE-MANUAL-1",
            "status": 100,
            "order_reference": "54321",
        }
    )
    fallback_calls: list[InvoiceSummary] = []
    monkeypatch.setattr(view, "_selected_summary", lambda: summary)
    monkeypatch.setattr(
        view,
        "_load_sevdesk_context",
        lambda invoice, _seq: fallback_calls.append(invoice),
    )
    view._wix_context_seq = 3  # noqa: SLF001

    view._on_wix_context_loaded(  # noqa: SLF001
        {
            "seq": 3,
            "__requested_ref": "54321",
            "status": "",
            "meta": {},
            "items": [],
        }
    )

    assert fallback_calls == [summary]
    cached = view._get_cached_wix_context("54321")  # noqa: SLF001
    assert cached is not None
    assert cached["status"] == "Wix-Order nicht gefunden"


def test_wix_order_button_requires_confirmed_context(
    qtbot: object, monkeypatch: MonkeyPatch
) -> None:
    view = RechnungenView(_build_container())
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "manual-reference-button",
            "invoiceNumber": "RE-MANUAL-2",
            "order_reference": "54321",
        }
    )
    monkeypatch.setattr(view, "_selected_summary", lambda: summary)

    view._update_plc_controls()  # noqa: SLF001

    assert view._btn_open_wix_order.isHidden()  # noqa: SLF001
    assert not view._btn_open_wix_order.isEnabled()  # noqa: SLF001


def test_rechnungen_applies_persistent_wix_cache_before_background_load(
    qtbot: object,
    monkeypatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    # This test covers the persistent Wix cache; keep the unrelated first-use
    # catalog disk/settings warm-up out of its background-worker lifecycle.
    container.resolve(ProductCatalogService).list_unreleased_products()
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
    qtbot.waitUntil(lambda: view._piece_model.rowCount() == 1, timeout=3000)  # noqa: SLF001
    qtbot.waitUntil(lambda: view._piece_config_worker is None, timeout=3000)  # noqa: SLF001
    assert view._piece_model.rowCount() == 1  # noqa: SLF001
    assert "Cache Produkt" in str(view._piece_model.index(0, 0).data())  # noqa: SLF001
    assert not view._piece_list.isHidden()  # noqa: SLF001
    assert not view._gb_stuecke.isHidden()  # noqa: SLF001
    assert view._get_cached_wix_context("20899") is not None  # noqa: SLF001
    assert load_calls == []
    view.request_shutdown()
    qtbot.waitUntil(view.shutdown_complete, timeout=3000)


def test_shipping_editor_keeps_complete_panel_address_over_name_only_wix() -> None:
    panel_lines = ["Anja Gundermann", "Storchenblick 30", "21243 Winsen", "GERMANY"]
    wix_lines = ["Dr. Werner Scheitzeneider"]

    assert RechnungenView._should_replace_shipping_lines(panel_lines, wix_lines) is False  # noqa: SLF001
    assert RechnungenView._should_replace_shipping_lines([], wix_lines) is True  # noqa: SLF001


def test_rechnungen_wix_shipping_address_replaces_sevdesk_prefill(
    qtbot: object,
    monkeypatch,
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summary = InvoiceSummary.model_validate(
        {
            "id": "wix-shipping-source",
            "invoiceNumber": "RE-WIX-SHIPPING",
            "status": 200,
            "contact_name": "sevDesk Kunde",
            "order_reference": "20977",
        }
    )
    monkeypatch.setattr(view, "_hydrate_detail_for_selection", lambda *_args: None)
    view._summaries = [summary]  # noqa: SLF001
    view._table.set_data([summary.as_table_row()])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    view._shipping_source_lines = [  # noqa: SLF001
        "sevDesk Kunde",
        "Rechnungsweg 1",
        "5020 Salzburg",
        "AUSTRIA",
    ]
    view._set_shipping_editor_lines(view._shipping_source_lines)  # noqa: SLF001

    view._on_wix_meta_loaded(  # noqa: SLF001
        {
            "__requested_ref": "20977",
            "wix_order_number": "20977",
            "wix_customer_name": "Wix Kunde",
            "wix_customer_email": "wix@example.test",
            "wix_shipping_country": "Austria",
            "wix_shipping_address": "Wix Kunde\nLiefergasse 7\n1010 Wien\nAUSTRIA",
        }
    )

    assert view._current_shipping_lines() == [  # noqa: SLF001
        "Wix Kunde",
        "Liefergasse 7",
        "1010 Wien",
        "AUSTRIA",
    ]
    assert view._shipping_status.text() == "Adresse aus Wix"  # noqa: SLF001


def test_rechnungen_piece_details_use_model_instead_of_row_widgets(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_load_wix_context", lambda *_args, **_kwargs: None)
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
    entered, release, heartbeat = Event(), Event(), Event()

    def blocked_resolver(catalog: ProductCatalogService, piece: PieceBlock) -> PieceBlock:
        del catalog
        entered.set()
        assert release.wait(3)
        piece.product = Product(id=piece.sku, sku=piece.sku, name=piece.name)
        return piece

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.resolve_piece_print_config", blocked_resolver
    )
    view._on_stuecke_loaded({"__requested_ref": "20999", "items": pieces})  # noqa: SLF001
    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        assert view._piece_model.rowCount() == 0  # noqa: SLF001
    finally:
        release.set()
    qtbot.waitUntil(
        lambda: view._piece_model.rowCount() == 100
        or "Produktdaten konnten nicht geladen" in view._stuecke_hint.text(),
        timeout=5000,
    )
    assert view._piece_model.rowCount() == 100, view._stuecke_hint.text()  # noqa: SLF001
    assert view._piece_model.rowCount() == 100  # noqa: SLF001
    assert view._stuecke_layout.count() == 2  # noqa: SLF001
    assert not view._piece_list.isHidden()  # noqa: SLF001


def test_open_product_enrichment_runs_off_ui_thread_and_discards_stale_result(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    first = PrintProductAggregate(sku="XW-OLD", title="Alt", description="", quantity=1)
    latest = PrintProductAggregate(sku="XW-LATEST", title="Aktuell", description="", quantity=1)
    latest_overview = OpenInvoiceOverview(
        key="latest", total=1, with_ref=1, physical=1, digital=0,
        unknown=0, with_note=0, plc=0, complete=True, print_products=[latest],
    )
    entered, release, heartbeat = Event(), Event(), Event()

    def blocked(items: list[PrintProductAggregate]) -> dict[tuple[str, str, str], PieceBlock]:
        for item in items:
            if item.sku == first.sku:
                entered.set()
                assert release.wait(3)
        return {
            view._open_product_check_key(item): PieceBlock(  # noqa: SLF001
                sku=str(item.sku), name=str(item.title), qty_needed=1
            )
            for item in items
        }

    monkeypatch.setattr(view, "_resolve_piece_blocks_from_open_products", blocked)
    monkeypatch.setattr(view, "_resolve_open_print_product_ready", lambda _item: True)
    view._apply_open_invoice_overview(
        OpenInvoiceOverview(
            key="slow-old", total=1, with_ref=1, physical=1, digital=0,
            unknown=0, with_note=0, plc=0, complete=True, print_products=[first],
        )
    )
    try:
        qtbot.waitUntil(entered.is_set, timeout=2000)
        QTimer.singleShot(0, heartbeat.set)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
        assert view._open_products_rows_layout.count() >= 2  # noqa: SLF001
        view._apply_open_invoice_overview(latest_overview)
    finally:
        release.set()

    qtbot.waitUntil(
        lambda: view._open_product_prepared_target
        == view._open_product_preparation_key(latest_overview),
        timeout=5000,
    )
    assert view._open_product_check_key(latest) in view._open_product_prepared_blocks  # noqa: SLF001
    assert view._open_product_check_key(first) not in view._open_product_prepared_blocks  # noqa: SLF001


def test_open_print_product_row_uses_cached_catalog_title_without_ui_resolution(
    qtbot: QtBot,
    monkeypatch: MonkeyPatch,
) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    container.reset()
    original_resolve = container.resolve

    def checked_resolve(service_type: type[object]) -> object:
        if service_type is ProductCatalogService and container.get_if_resolved(ProductCatalogService) is None:
            raise AssertionError("Der Print-Produkte-Zeilenaufbau darf den Katalog nicht aufloesen")
        return original_resolve(service_type)

    monkeypatch.setattr(container, "resolve", checked_resolve)
    item = PrintProductAggregate(sku="XW-010", title="Kundenangabe aus Wix", description="", quantity=1)
    key = view._open_product_check_key(item)  # noqa: SLF001
    view._open_product_prepared_blocks[key] = PieceBlock(  # noqa: SLF001
        sku="XW-010", name="Kanonischer Titel", qty_needed=1
    )

    row = view._build_open_print_product_row(item)  # noqa: SLF001
    labels = [label.text() for label in row.findChildren(QLabel)]

    assert "Kanonischer Titel" in labels
    assert "Kundenangabe: Kundenangabe aus Wix" in labels
    assert container.get_if_resolved(ProductCatalogService) is None


def test_late_invoice_product_configuration_is_discarded_after_selection_change(
    qtbot: QtBot, monkeypatch: MonkeyPatch
) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_load_wix_context", lambda *_args, **_kwargs: None)
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": f"piece-{key}",
                "invoiceNumber": f"RE-{key}",
                "status": 1000,
                "order_reference": key,
            }
        )
        for key in ("A", "B")
    ]
    view._summaries = summaries  # noqa: SLF001
    view._table.set_data([summary.as_table_row() for summary in summaries])  # noqa: SLF001
    view._table.select_source_row(0)  # noqa: SLF001
    entered, release = Event(), Event()

    def resolver(catalog: ProductCatalogService, piece: PieceBlock) -> PieceBlock:
        del catalog
        if piece.sku == "SKU-A":
            entered.set()
            assert release.wait(3)
        piece.product = Product(id=piece.sku, sku=piece.sku, name=piece.name)
        return piece

    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.view.resolve_piece_print_config", resolver
    )
    try:
        view._on_stuecke_loaded(  # noqa: SLF001
            {
                "__requested_ref": "A",
                "items": [PieceBlock(sku="SKU-A", name="Invoice A", qty_needed=1)],
            }
        )
        qtbot.waitUntil(entered.is_set, timeout=2000)
        view._table.select_source_row(1)  # noqa: SLF001
        view._on_stuecke_loaded(  # noqa: SLF001
            {
                "__requested_ref": "B",
                "items": [PieceBlock(sku="SKU-B", name="Invoice B", qty_needed=1)],
            }
        )
    finally:
        release.set()

    qtbot.waitUntil(lambda: view._piece_model.rowCount() == 1, timeout=3000)  # noqa: SLF001
    assert "Invoice B" in str(view._piece_model.index(0, 0).data())  # noqa: SLF001


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
    qtbot.waitUntil(view.shutdown_complete, timeout=3000)


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


def test_invoice_list_secret_check_runs_off_ui_thread(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    container, invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    entered = Event()
    release = Event()
    heartbeat = Event()

    def blocked_secret_read() -> bool:
        entered.set()
        release.wait(timeout=3)
        return True

    monkeypatch.setattr(view, "_has_sevdesk_token", blocked_secret_read)
    QTimer.singleShot(0, heartbeat.set)
    view._start_load(limit=1)  # noqa: SLF001

    try:
        assert entered.wait(timeout=1)
        qtbot.waitUntil(heartbeat.is_set, timeout=1000)
    finally:
        release.set()

    qtbot.waitUntil(lambda: view._worker is None, timeout=3000)  # noqa: SLF001
    assert invoice_service.load_calls == [("status:100", 1, 0)]


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


def test_50_prepared_invoice_rows_apply_within_gui_block_budget(qtbot: QtBot) -> None:
    container, _invoice_service = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    summaries = [
        InvoiceSummary.model_validate(
            {
                "id": str(1000 + index),
                "invoiceNumber": f"RE-{1000 + index}",
                "invoiceDate": f"2026-08-{(index % 28) + 1:02}T12:00:00",
                "status": 1000,
                "contact_name": f"Kunde {index:02}",
            }
        )
        for index in range(50)
    ]
    rows = [summary.as_table_row() for summary in summaries]

    started = perf_counter()
    view._apply_load_result_data(  # noqa: SLF001
        rows,
        summaries,
        True,
        1000,
        False,
        allow_background_prefetch=False,
    )
    elapsed_ms = (perf_counter() - started) * 1000

    assert view._table.model().sourceModel().rowCount() == 50  # noqa: SLF001
    assert elapsed_ms < 250, f"50 vorbereitete Rechnungszeilen blockierten {elapsed_ms:.1f} ms"


def test_rechnungen_clearing_search_restores_staged_drafts_and_recent_invoices(
    qtbot: object,
) -> None:
    container = _build_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)

    draft = InvoiceSummary.model_validate(
        {
            "id": "11",
            "invoiceNumber": "RE-DRAFT",
            "invoiceDate": "2026-06-01T00:00:00",
            "status": 100,
            "contact_name": "Draft Customer",
        }
    )
    recent_invoice = InvoiceSummary.model_validate(
        {
            "id": "99",
            "invoiceNumber": "RE-RECENT",
            "invoiceDate": "2026-07-01T00:00:00",
            "status": 1000,
            "contact_name": "Recent Customer",
        }
    )
    search_result = InvoiceSummary.model_validate(
        {
            "id": "55",
            "invoiceNumber": "RE-SEARCH",
            "invoiceDate": "2026-08-01T00:00:00",
            "status": 1000,
            "contact_name": "Search Customer",
        }
    )

    view._apply_load_result_data(  # noqa: SLF001
        [draft.as_table_row()],
        [draft],
        False,
        100,
        False,
        allow_background_prefetch=False,
    )
    view._apply_load_result_data(  # noqa: SLF001
        [recent_invoice.as_table_row()],
        [recent_invoice],
        False,
        None,
        True,
        allow_background_prefetch=False,
    )

    view._search_active = True  # noqa: SLF001
    view._table.set_data([search_result.as_table_row()])  # noqa: SLF001
    view._summaries = [search_result]  # noqa: SLF001

    view._on_search("")  # noqa: SLF001

    assert [summary.invoice_number for summary in view._summaries] == [
        "RE-RECENT",
        "RE-DRAFT",
    ]
    assert view._table.model().sourceModel().rowCount() == 2  # noqa: SLF001


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

    # MainWindow drains background work asynchronously before it accepts a
    # close.  Let that contract complete instead of letting pytest-qt delete a
    # live QThread during fixture teardown.
    window.close()
    qtbot.waitUntil(lambda: window._shutdown_finished, timeout=5000)  # noqa: SLF001


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

    monkeypatch.setattr("xw_office.ui.modules.rechnungen.view._CustomLabelDialog.exec", fake_exec)

    view._print_allowed = False  # noqa: SLF001
    view._on_custom_label_clicked()  # noqa: SLF001

    assert called["count"] == 1

def test_inventory_badge_load_keeps_gui_responsive_and_coalesces(
    qtbot: QtBot, monkeypatch: MonkeyPatch,
) -> None:
    from xw_office.services.product_hub.inventory import InventoryV2Service

    container, _service = _build_rechnungen_test_container()
    entered, release = Event(), Event()
    calls = []

    class SlowInventory:
        def list_open_alert_details(self) -> list[object]:
            calls.append(1)
            entered.set()
            assert release.wait(3)
            return [object(), object()]

    container.register(InventoryV2Service, lambda _: SlowInventory())
    view = RechnungenView(container)
    qtbot.addWidget(view)
    # Construction and hidden widgets must not start recurring database work.
    assert calls == []
    assert not view._inventory_alert_timer.isActive()
    heartbeat = []
    try:
        view._refresh_inventory_alert_count()
        qtbot.waitUntil(entered.is_set)
        view._refresh_inventory_alert_count()
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert calls == [1]
        assert view._inventory_alert_worker in view._shutdown_workers()
    finally:
        release.set()
        qtbot.waitUntil(lambda: view._inventory_alert_worker is None)
    assert view._btn_inventory_alert.text() == 'LAGERALARME (2)'
    view._on_inventory_alert_error(RuntimeError('DB unavailable'))
    assert view._btn_inventory_alert.text() == 'LAGERALARME (?)'
    assert 'DB unavailable' in view._btn_inventory_alert.toolTip()


def test_old_sevdesk_worker_finish_does_not_clear_new_request(
    qtbot: QtBot, monkeypatch: MonkeyPatch,
) -> None:
    from xw_office.services.invoice_processing.context import InvoiceWorkContext

    container, service = _build_rechnungen_test_container()
    entered = [Event(), Event()]
    releases = [Event(), Event()]

    def load(summary: InvoiceSummary, **kwargs: object) -> InvoiceWorkContext:
        index = int(summary.id)
        entered[index].set()
        assert releases[index].wait(3)
        return InvoiceWorkContext(summary=summary, origin='sevdesk_only')

    monkeypatch.setattr(service, 'load_invoice_work_context', load, raising=False)
    monkeypatch.setattr(service, 'load_invoice_piece_blocks', lambda _: [], raising=False)
    view = RechnungenView(container)
    qtbot.addWidget(view)
    old = new = None
    try:
        view._sevdesk_context_seq += 1
        view._load_sevdesk_context(InvoiceSummary(id='0'), 1)
        old = view._stuecke_worker
        qtbot.waitUntil(entered[0].is_set)
        view._sevdesk_context_seq += 1
        view._load_sevdesk_context(InvoiceSummary(id='1'), 2)
        new = view._stuecke_worker
        qtbot.waitUntil(entered[1].is_set)
        assert old in view._shutdown_workers()
        assert new in view._shutdown_workers()
        releases[0].set()
        qtbot.waitUntil(lambda: old not in view._sevdesk_context_workers)
        assert view._stuecke_worker is new
    finally:
        for release in releases:
            release.set()
        qtbot.waitUntil(lambda: not view._sevdesk_context_workers)
        view.request_shutdown()
        qtbot.waitUntil(view.shutdown_complete, timeout=3000)
    assert view._stuecke_worker is None


def test_sevdesk_context_displays_all_position_details(qtbot: QtBot, monkeypatch: MonkeyPatch) -> None:
    summary = InvoiceSummary(id="invoice-details", invoiceNumber="RE-DETAILS")
    position = InvoiceWorkPosition(
        source_id="invoice-pos-1",
        position_number=2,
        part_id="part-9",
        sku="XW-010",
        sku_source="part.partNumber",
        name="Notenheft",
        description="Ausgabe 2026",
        quantity=Decimal("1.5"),
        kind="product",
        printable=False,
        unit_weight_kg=0.25,
        unit_value=Decimal("12.50"),
        unit="Stück",
        unit_price_net=Decimal("10.42"),
        unit_price_gross=Decimal("12.50"),
        unit_tax=Decimal("2.08"),
        tax_rate=Decimal("20"),
        discount=Decimal("5"),
        sum_discount=Decimal("0.63"),
        sum_net_accounting=Decimal("15.63"),
        sum_tax_accounting=Decimal("3.12"),
        sum_gross_accounting=Decimal("18.75"),
        warnings=("Bruchmenge muss geprueft werden",),
    )
    context = InvoiceWorkContext(
        summary=summary,
        origin="sevdesk_only",
        positions=(position,),
        positions_loaded=True,
    )
    container, _ = _build_rechnungen_test_container()
    view = RechnungenView(container)
    qtbot.addWidget(view)
    monkeypatch.setattr(view, "_selected_summary", lambda: summary)
    monkeypatch.setattr(view, "_update_plc_controls", lambda: None)

    view._on_sevdesk_context_loaded(
        {
            "context_seq": view._sevdesk_context_seq,
            "invoice_id": summary.id,
            "context": context,
            "items": [],
        }
    )

    rendered = view._stuecke_hint.text()
    for detail in (
        "Pos. 2: Notenheft",
        "Menge: 1.5",
        "SKU: XW-010",
        "Beschreibung: Ausgabe 2026",
        "InvoicePos-ID: invoice-pos-1",
        "Part-ID: part-9",
        "Gewicht: 0.25 kg",
        "Einheit: Stück",
        "Einzelpreis netto: 10.42 EUR",
        "Einzelpreis brutto: 12.50 EUR",
        "Einzelsteuer: 2.08 EUR",
        "Steuersatz: 20%",
        "Rabatt: 5%",
        "Rabattbetrag: 0.63 EUR",
        "Positionssumme netto: 15.63 EUR",
        "Positionssteuer: 3.12 EUR",
        "Positionssumme brutto: 18.75 EUR",
        "Bruchmenge muss geprueft werden",
    ):
        assert detail in rendered
    assert not view._stuecke_hint.isHidden()

def test_draft_preview_is_invalidated_when_order_number_changes(qtbot: QtBot) -> None:
    dialog = _DraftInvoiceDialog()
    qtbot.addWidget(dialog)
    dialog._order_number.setText('12345')
    dialog.set_preview_result('Preview for first order', ok=True)
    assert dialog.preview_ok
    dialog._order_number.setText('54321')
    assert not dialog.preview_ok
    dialog._accept_if_valid()
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.set_preview_result('Preview for second order', ok=True)
    dialog._accept_if_valid()
    assert dialog.result() == QDialog.DialogCode.Accepted
