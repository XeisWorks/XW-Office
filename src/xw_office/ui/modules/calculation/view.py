"""Provisionen / Kalkulation module."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from openpyxl import Workbook

from xw_office.core.worker import BackgroundWorker
from xw_office.services.commission.service import (
    CommissionRunResult,
    CommissionService,
    format_euro_amount,
    format_commission_summary,
    format_quantity,
)
from xw_office.services.expenses.service import BankExpenseRow, ExpenseAuditService
from xw_office.services.calculation.service import (
    ArticleEntry,
    CalculationService,
    calculate_royalty,
)
from xw_office.services.products.catalog import ProductCatalogService
from xw_office.ui.dialogs.unreleased_title_dialog import (
    UnreleasedTitleDialog,
    UnreleasedTitleSplitDialog,
)
from xw_office.ui.widgets.data_table import DataTable

if TYPE_CHECKING:
    from xw_office.core.container import Container

logger = logging.getLogger(__name__)

_ARTICLE_HEADERS = [
    "Titel",
    "Brutto EUR",
    "MwSt %",
    "Provision %",
    "Netto EUR",
    "MwSt EUR",
    "Provision EUR",
    "Notiz",
]
_PRODUCT_HEADERS = ["SKU", "Name", "Verkauft", "Netto"]
_CATEGORY_HEADERS = ["Kategorie", "Menge", "Netto", "Brutto"]
_DOC_HEADERS = ["Beleg", "Datum", "Typ", "SKU", "Menge", "Netto", "Regel"]


class CalculationView(QWidget):
    """Commission workspace with grouped navigation and calculators."""

    def __init__(self, container: Container, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._container = container
        self._commission_service: CommissionService = self._container.resolve(CommissionService)
        self._articles: list[ArticleEntry] = []
        self._worker: BackgroundWorker | None = None
        self._commission_worker: BackgroundWorker | None = None
        self._embedded_expense_worker: BackgroundWorker | None = None
        self._export_worker: BackgroundWorker | None = None
        self._last_commission_result: CommissionRunResult | None = None
        self._active_profile_key: str = ""
        self._rerun_commission_after_clarification = False
        self._dismissed_unreleased_issues: set[tuple[str, str, str]] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        nav_wrap = QWidget()
        nav_lay = QVBoxLayout(nav_wrap)
        nav_lay.setContentsMargins(0, 0, 0, 0)
        nav_lay.setSpacing(6)
        nav_title = QLabel("Provisionen")
        nav_title.setStyleSheet("font-weight: 600;")
        nav_lay.addWidget(nav_title)

        self._nav_filter = QLineEdit()
        self._nav_filter.setPlaceholderText("Auswahl filtern...")
        self._nav_filter.textChanged.connect(self._apply_nav_filter)
        nav_lay.addWidget(self._nav_filter)

        self._nav = QListWidget()
        self._nav.setAlternatingRowColors(False)
        self._nav.currentRowChanged.connect(self._on_nav_changed)
        nav_lay.addWidget(self._nav, stretch=1)
        nav_wrap.setMinimumWidth(240)
        nav_wrap.setMaximumWidth(320)

        self._stack = QStackedWidget()
        self._commission_page_index = self._stack.addWidget(self._build_musikheroes_page())
        self._add_nav_header("Abrechnungen")
        profiles = self._commission_service.list_profiles()
        for profile in profiles:
            self._add_nav_entry(
                profile.label,
                page_index=self._commission_page_index,
                kind="profile",
                key=profile.key,
            )

        self._add_nav_header("Kalkulatoren")
        self._add_nav_entry(
            "Artikelliste",
            page_index=self._stack.addWidget(self._build_articles_tab()),
            kind="page",
            key="articles",
        )
        self._add_nav_entry(
            "Schnellrechner",
            page_index=self._stack.addWidget(self._build_calc_tab()),
            kind="page",
            key="quickcalc",
        )

        if profiles:
            self._active_profile_key = profiles[0].key
            self._commission_title.setText(f"{profiles[0].label} Abrechnung")

        splitter.addWidget(nav_wrap)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self._select_first_nav_page()

        self._load_articles()

    def _add_nav_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setData(Qt.ItemDataRole.UserRole, {"kind": "header"})
        self._nav.addItem(item)

    def _add_nav_entry(self, text: str, *, page_index: int, kind: str, key: str) -> None:
        item = QListWidgetItem(f"  {text}")
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "kind": kind,
                "key": key,
                "page_index": page_index,
                "label": text,
            },
        )
        self._nav.addItem(item)

    def _apply_nav_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._nav.count()):
            item = self._nav.item(row)
            payload = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("kind") or "")
            if kind == "header":
                item.setHidden(False)
                continue
            label = str(payload.get("label") or item.text()).strip().lower()
            item.setHidden(bool(needle) and needle not in label)

    def _select_first_nav_page(self) -> None:
        for row in range(self._nav.count()):
            item = self._nav.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict) and str(data.get("kind") or "") in {"page", "profile"}:
                self._nav.setCurrentRow(row)
                return

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._nav.item(row)
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("kind") or "")
        page_index = payload.get("page_index")
        if not isinstance(page_index, int):
            return
        self._stack.setCurrentIndex(page_index)
        if kind == "profile":
            key = str(payload.get("key") or "").strip()
            if key:
                self._active_profile_key = key
                profile = self._commission_service.get_profile(key)
                self._commission_title.setText(f"{profile.label} Abrechnung")

    # ------------------------------------------------------------------
    # Commission page: MusikHeroes
    # ------------------------------------------------------------------

    def _build_musikheroes_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        self._commission_title = QLabel("Abrechnung")
        self._commission_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(self._commission_title)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Zeitraum:"))
        self._period_combo = QComboBox()
        self._period_combo.addItem("Letzter Monat", "last_month")
        self._period_combo.addItem("Letztes Quartal", "last_quarter")
        self._period_combo.addItem("Letztes Halbjahr", "last_half_year")
        self._period_combo.addItem("Letztes Jahr", "last_year")
        self._period_combo.addItem("Benutzerdefiniert", "custom")
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        controls.addWidget(self._period_combo)

        controls.addWidget(QLabel("Stichtag:"))
        self._reference_date = QDateEdit()
        self._reference_date.setCalendarPopup(True)
        self._reference_date.setDate(self._reference_date.date().currentDate())
        controls.addWidget(self._reference_date)

        controls.addWidget(QLabel("Von:"))
        self._custom_start = QDateEdit()
        self._custom_start.setCalendarPopup(True)
        self._custom_start.setEnabled(False)
        controls.addWidget(self._custom_start)

        controls.addWidget(QLabel("Bis:"))
        self._custom_end = QDateEdit()
        self._custom_end.setCalendarPopup(True)
        self._custom_end.setEnabled(False)
        controls.addWidget(self._custom_end)
        controls.addStretch()
        lay.addLayout(controls)

        toggles = QHBoxLayout()
        self._include_cancellations = QCheckBox("Stornos einbeziehen")
        self._include_cancellations.setChecked(True)
        toggles.addWidget(self._include_cancellations)
        self._include_credit_notes = QCheckBox("Gutschriften einbeziehen")
        self._include_credit_notes.setChecked(True)
        toggles.addWidget(self._include_credit_notes)
        self._show_anomalies = QCheckBox("Problemfaelle anzeigen")
        self._show_anomalies.setChecked(True)
        toggles.addWidget(self._show_anomalies)
        toggles.addStretch()

        run_btn = QPushButton("Neu laden")
        run_btn.clicked.connect(lambda: self._run_musikheroes(use_cache=False))
        toggles.addWidget(run_btn)
        cache_btn = QPushButton("Cache verwenden")
        cache_btn.clicked.connect(lambda: self._run_musikheroes(use_cache=True))
        toggles.addWidget(cache_btn)
        export_csv_btn = QPushButton("CSV")
        export_csv_btn.setToolTip("Abrechnung als CSV exportieren")
        export_csv_btn.clicked.connect(self._export_commission_csv)
        toggles.addWidget(export_csv_btn)
        export_xlsx_btn = QPushButton("XLSX")
        export_xlsx_btn.setToolTip("Abrechnung als Excel-Datei exportieren")
        export_xlsx_btn.clicked.connect(self._export_commission_xlsx)
        toggles.addWidget(export_xlsx_btn)
        lay.addLayout(toggles)

        self._commission_status = QLabel("Noch nicht geladen")
        self._commission_status.setWordWrap(True)

        result_splitter = QSplitter(Qt.Orientation.Horizontal)
        result_splitter.setChildrenCollapsible(False)

        overview = QWidget()
        overview_lay = QVBoxLayout(overview)
        overview_lay.setContentsMargins(0, 0, 0, 0)
        overview_lay.setSpacing(8)
        overview_lay.addWidget(self._commission_status)
        self._category_table = DataTable(_CATEGORY_HEADERS)
        self._category_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._category_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        overview_lay.addWidget(self._category_table, stretch=1)
        copy_btn = QPushButton("In Zwischenablage kopieren")
        copy_btn.setToolTip("Kompakte Abrechnung inklusive Produktliste kopieren")
        copy_btn.clicked.connect(self._copy_commission_summary)
        overview_lay.addWidget(copy_btn)

        products = QWidget()
        products_lay = QVBoxLayout(products)
        products_lay.setContentsMargins(0, 0, 0, 0)
        products_lay.setSpacing(8)
        products_lay.addWidget(QLabel("Produkte"))
        self._product_table = DataTable(_PRODUCT_HEADERS)
        self._product_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._product_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._product_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        products_lay.addWidget(self._product_table, stretch=1)

        result_splitter.addWidget(overview)
        result_splitter.addWidget(products)
        result_splitter.setStretchFactor(0, 1)
        result_splitter.setStretchFactor(1, 2)
        result_splitter.setSizes([430, 760])
        lay.addWidget(result_splitter, stretch=4)

        self._embedded_expenses_group = QGroupBox("Ausgaben MusikHeroes")
        self._embedded_expenses_group.setCheckable(True)
        self._embedded_expenses_group.setChecked(True)
        expenses_layout = QVBoxLayout(self._embedded_expenses_group)
        self._embedded_expenses_status = QLabel("Noch nicht geladen")
        expenses_layout.addWidget(self._embedded_expenses_status)
        self._embedded_expenses_table = DataTable(
            ["Datum", "Empfänger", "Zahlungsreferenz / Verwendungszweck", "Betrag", "Flag", "Beleg"]
        )
        self._embedded_expenses_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        expenses_layout.addWidget(self._embedded_expenses_table)
        expense_actions = QHBoxLayout()
        include_expense = QPushButton("MusikHeroes einschließen")
        include_expense.clicked.connect(lambda: self._flag_embedded_expense(True))
        exclude_expense = QPushButton("MusikHeroes ausschließen")
        exclude_expense.clicked.connect(lambda: self._flag_embedded_expense(False))
        expense_actions.addWidget(include_expense)
        expense_actions.addWidget(exclude_expense)
        expense_actions.addStretch()
        expenses_layout.addLayout(expense_actions)
        lay.addWidget(self._embedded_expenses_group)

        self._documents_group = QGroupBox("Belege")
        self._documents_group.setCheckable(True)
        self._documents_group.setChecked(False)
        documents_lay = QVBoxLayout(self._documents_group)
        self._doc_table = DataTable(_DOC_HEADERS)
        self._doc_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Interactive
        )
        self._doc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._doc_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._doc_table.setVisible(False)
        self._documents_group.toggled.connect(self._doc_table.setVisible)
        documents_lay.addWidget(self._doc_table)
        lay.addWidget(self._documents_group)

        self._anomaly_label = QLabel("Problemfaelle:")
        lay.addWidget(self._anomaly_label)
        self._anomaly_table = DataTable(["Hinweis"])
        self._anomaly_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._anomaly_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        lay.addWidget(self._anomaly_table, stretch=1)

        return page

    def _on_period_changed(self) -> None:
        is_custom = self._period_combo.currentData() == "custom"
        self._custom_start.setEnabled(bool(is_custom))
        self._custom_end.setEnabled(bool(is_custom))

    def _run_musikheroes(self, *, use_cache: bool) -> None:
        if self._commission_worker is not None and self._commission_worker.isRunning():
            return
        if not use_cache:
            self._dismissed_unreleased_issues.clear()
        commission = self._commission_service
        if not self._active_profile_key:
            QMessageBox.warning(self, "Provisionen", "Kein Abrechnungsprofil ausgewaehlt.")
            return

        period_key = str(self._period_combo.currentData() or "last_month")
        reference = self._reference_date.date().toPython()
        custom_start = self._custom_start.date().toPython() if period_key == "custom" else None
        custom_end = self._custom_end.date().toPython() if period_key == "custom" else None

        try:
            period = commission.resolve_period(
                period_key,
                reference_date=reference,
                custom_start=custom_start,
                custom_end=custom_end,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Provisionen", str(exc))
            return

        profile_label = commission.get_profile(self._active_profile_key).label
        self._commission_status.setText(f"{profile_label}-Abrechnung wird geladen...")
        profile_key = self._active_profile_key
        include_cancellations = self._include_cancellations.isChecked()
        include_credit_notes = self._include_credit_notes.isChecked()

        def job() -> CommissionRunResult:
            return commission.run_profile(
                profile_key,
                period,
                include_cancellation_invoices=include_cancellations,
                include_credit_notes=include_credit_notes,
                refresh_data=not use_cache,
            )

        self._commission_worker = BackgroundWorker(job)
        self._commission_worker.signals.result.connect(self._on_musikheroes_loaded)
        self._commission_worker.signals.error.connect(self._on_error)
        self._commission_worker.signals.finished.connect(self._on_commission_finished)
        self._commission_worker.start()

    def _on_musikheroes_loaded(self, payload: object) -> None:
        if not isinstance(payload, CommissionRunResult):
            return
        if payload.unresolved_titles and self._clarify_unreleased_titles(payload):
            self._rerun_commission_after_clarification = True
            return
        self._last_commission_result = payload

        period = payload.period
        self._commission_status.setText(
            f"Kategorie: {payload.profile.label}\n"
            f"Zeitraum: {period.start.strftime('%d.%m.%Y')} - {period.end.strftime('%d.%m.%Y')}"
        )

        self._populate_product_table(payload)
        self._populate_category_table(payload)
        self._populate_doc_table(payload)
        self._populate_anomaly_table(payload)
        self._load_embedded_expenses(payload)

    def _load_embedded_expenses(self, result: CommissionRunResult) -> None:
        if self._embedded_expense_worker is not None and self._embedded_expense_worker.isRunning():
            return
        try:
            service: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        except KeyError:
            self._embedded_expenses_status.setText("Ausgabenpipeline nicht konfiguriert")
            return
        period = result.period
        self._embedded_expenses_status.setText("Ausgaben werden geladen …")
        self._embedded_expense_worker = BackgroundWorker(
            lambda: service.list_bank_expenses(
                start=period.start,
                end=period.end,
                profile_key=result.profile.key,
                refresh=True,
            )
        )
        self._embedded_expense_worker.signals.result.connect(self._on_embedded_expenses_loaded)
        self._embedded_expense_worker.signals.error.connect(
            lambda exc: self._embedded_expenses_status.setText(f"Ausgaben nicht verfügbar: {exc}")
        )
        self._embedded_expense_worker.signals.finished.connect(
            lambda: setattr(self, "_embedded_expense_worker", None)
        )
        self._embedded_expense_worker.start()

    def _on_embedded_expenses_loaded(self, payload: object) -> None:
        rows = [row for row in payload if isinstance(row, BankExpenseRow)] if isinstance(payload, list) else []
        self._embedded_expenses_table.set_data(
            [
                {
                    "Datum": row.value_date.strftime("%d.%m.%Y"),
                    "Empfänger": row.payee,
                    "Zahlungsreferenz / Verwendungszweck": row.purpose,
                    "Betrag": format_euro_amount(row.amount),
                    "Flag": row.profile_status or "—",
                    "Beleg": "sevDesk" if row.sevdesk_url else ("Lieferantenportal" if row.supplier_url else "fehlt"),
                    "__transaction_id": row.transaction_id,
                    "__iban": row.iban,
                    "__payee": row.payee,
                    "__align__Betrag": "right",
                }
                for row in rows
            ]
        )
        self._embedded_expenses_status.setText(
            f"{len(rows)} ausgehende Zahlungen · informativ, nicht provisionswirksam"
        )

    def _flag_embedded_expense(self, include: bool) -> None:
        selected = self._embedded_expenses_table.selected_row_data()
        if not selected:
            QMessageBox.information(self, "Provisionen", "Bitte zuerst eine Ausgabe auswählen.")
            return
        try:
            service: ExpenseAuditService = self._container.resolve(ExpenseAuditService)
        except KeyError:
            return
        service.flag_profile_transaction(
            transaction_id=str(selected.get("__transaction_id") or ""),
            profile_key=self._active_profile_key or "musikheroes",
            payee=str(selected.get("__payee") or ""),
            iban=str(selected.get("__iban") or ""),
            include=include,
        )
        if self._last_commission_result is not None:
            self._load_embedded_expenses(self._last_commission_result)

    def _clarify_unreleased_titles(self, result: CommissionRunResult) -> bool:
        try:
            catalog: ProductCatalogService = self._container.resolve(ProductCatalogService)
        except KeyError:
            return False
        changed = False
        seen: set[tuple[str, str, str]] = set()
        for issue in result.unresolved_titles or []:
            key = (issue.raw_title, issue.order_reference, issue.document_number)
            if key in seen or key in self._dismissed_unreleased_issues:
                continue
            seen.add(key)
            context = (
                f"Beleg: {issue.document_number} · Wix: {issue.order_reference or 'keine Referenz'} "
                f"· SKU: {issue.sku}\nGrund: {issue.reason}"
            )
            if issue.needs_title_split:
                split_dialog = UnreleasedTitleSplitDialog(
                    quantity=issue.quantity,
                    initial_text=issue.raw_title,
                    context=context,
                    parent=self,
                )
                titles = split_dialog.titles()
                if titles is None:
                    self._dismissed_unreleased_issues.add(key)
                    continue
                catalog.save_unreleased_document_title(
                    issue.order_reference or issue.document_number,
                    "\n".join(titles),
                )
                changed = True
                continue
            dialog = UnreleasedTitleDialog(
                catalog,
                raw_title=issue.raw_title,
                context=context,
                parent=self,
            )
            decision = dialog.decision()
            if decision is None:
                self._dismissed_unreleased_issues.add(key)
                continue
            catalog.save_unreleased_resolution(
                decision.raw_title,
                canonical_name=decision.canonical_name,
                owner=decision.owner,
            )
            changed = True
        return changed

    def _on_commission_finished(self) -> None:
        self._commission_worker = None
        if not self._rerun_commission_after_clarification:
            return
        self._rerun_commission_after_clarification = False
        QTimer.singleShot(0, lambda: self._run_musikheroes(use_cache=True))

    def _export_commission_csv(self) -> None:
        result = self._last_commission_result
        if result is None:
            QMessageBox.information(self, "Provisionen", "Bitte zuerst eine Abrechnung laden.")
            return
        if self._export_worker is not None and self._export_worker.isRunning():
            return

        default_name = f"provision_{result.profile.key}_{result.period.start.isoformat()}_{result.period.end.isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren", default_name, "CSV (*.csv)")
        if not path:
            return

        def job() -> str:
            rows = [
                [
                    "sku",
                    "name",
                    "menge",
                    "netto",
                ]
            ]
            for row in result.product_rows:
                rows.append(
                    [
                        row.sku,
                        row.name,
                        f"{format_quantity(row.net_quantity)} Stk.",
                        format_euro_amount(row.net_amount),
                    ]
                )
            with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerows(rows)
            return path

        self._export_worker = BackgroundWorker(job)
        self._export_worker.signals.result.connect(
            lambda payload: QMessageBox.information(
                self, "Provisionen", f"CSV exportiert: {payload}"
            )
        )
        self._export_worker.signals.error.connect(
            lambda exc: QMessageBox.critical(
                self, "Provisionen", f"CSV-Export fehlgeschlagen: {exc}"
            )
        )
        self._export_worker.signals.finished.connect(lambda: setattr(self, "_export_worker", None))
        self._export_worker.start()

    def _export_commission_xlsx(self) -> None:
        result = self._last_commission_result
        if result is None:
            QMessageBox.information(self, "Provisionen", "Bitte zuerst eine Abrechnung laden.")
            return
        if self._export_worker is not None and self._export_worker.isRunning():
            return

        default_name = f"provision_{result.profile.key}_{result.period.start.isoformat()}_{result.period.end.isoformat()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "XLSX exportieren", default_name, "Excel (*.xlsx)"
        )
        if not path:
            return

        def job() -> str:
            wb = Workbook()
            ws_products = wb.active
            ws_products.title = "Produkte"
            ws_products.append(
                [
                    "SKU",
                    "Name",
                    "Menge",
                    "Netto",
                ]
            )
            for row in result.product_rows:
                ws_products.append(
                    [
                        row.sku,
                        row.name,
                        row.net_quantity,
                        row.net_amount,
                    ]
                )

            ws_categories = wb.create_sheet("Kategorien")
            ws_categories.append(
                ["Kategorie", "Menge", "Netto EUR", "Brutto EUR", "Anteil Netto %"]
            )
            for row in result.category_rows:
                ws_categories.append(
                    [
                        row.category_name,
                        row.quantity,
                        row.net_amount,
                        row.gross_amount,
                        row.share_of_net_amount * 100.0,
                    ]
                )

            for sheet in (ws_products, ws_categories):
                for cell in sheet[1]:
                    cell.font = cell.font.copy(bold=True)
            for row_index in range(2, ws_products.max_row + 1):
                ws_products.cell(row_index, 3).number_format = '0'
                ws_products.cell(row_index, 4).number_format = '€ #,##0.00'
            for row_index in range(2, ws_categories.max_row + 1):
                ws_categories.cell(row_index, 2).number_format = '0'
                ws_categories.cell(row_index, 3).number_format = '€ #,##0.00'
                ws_categories.cell(row_index, 4).number_format = '€ #,##0.00'

            ws_docs = wb.create_sheet("Belege")
            ws_docs.append(["Beleg", "Datum", "Typ", "SKU", "Menge", "Netto", "Regel", "Warnung"])
            for row in result.document_rows:
                ws_docs.append(
                    [
                        row.document_number,
                        row.document_date,
                        row.document_type,
                        row.sku,
                        row.signed_quantity,
                        row.signed_net,
                        row.rule,
                        row.warning,
                    ]
                )

            ws_anomalies = wb.create_sheet("Problemfaelle")
            ws_anomalies.append(["Hinweis"])
            for warning in result.anomalies:
                ws_anomalies.append([warning])
            wb.save(path)
            return path

        self._export_worker = BackgroundWorker(job)
        self._export_worker.signals.result.connect(
            lambda payload: QMessageBox.information(
                self, "Provisionen", f"XLSX exportiert: {payload}"
            )
        )
        self._export_worker.signals.error.connect(
            lambda exc: QMessageBox.critical(
                self, "Provisionen", f"XLSX-Export fehlgeschlagen: {exc}"
            )
        )
        self._export_worker.signals.finished.connect(lambda: setattr(self, "_export_worker", None))
        self._export_worker.start()

    def _copy_commission_summary(self) -> None:
        result = self._last_commission_result
        if result is None:
            QMessageBox.information(self, "Provisionen", "Bitte zuerst eine Abrechnung laden.")
            return

        clipboard = QApplication.clipboard()
        clipboard.setText(format_commission_summary(result))
        QMessageBox.information(self, "Provisionen", "Abrechnung in die Zwischenablage kopiert.")

    def _populate_product_table(self, result: CommissionRunResult) -> None:
        self._product_table.set_data(
            [
                {
                    "SKU": row.sku,
                    "Name": row.name,
                    "Verkauft": f"{format_quantity(row.net_quantity)} Stk.",
                    "Netto": format_euro_amount(row.net_amount),
                    "__align__SKU": "left",
                    "__align__Verkauft": "right",
                    "__align__Netto": "right",
                    "__sort__Verkauft": row.net_quantity,
                    "__sort__Netto": row.net_amount,
                }
                for row in result.product_rows
            ]
        )

    def _populate_category_table(self, result: CommissionRunResult) -> None:
        self._category_table.set_data(
            [
                {
                    "Kategorie": row.category_name,
                    "Menge": f"{format_quantity(row.quantity)} Stk.",
                    "Netto": format_euro_amount(row.net_amount),
                    "Brutto": format_euro_amount(row.gross_amount),
                    "__align__Menge": "right",
                    "__align__Netto": "right",
                    "__align__Brutto": "right",
                    "__sort__Menge": row.quantity,
                    "__sort__Netto": row.net_amount,
                    "__sort__Brutto": row.gross_amount,
                }
                for row in result.category_rows
            ]
        )

    def _populate_doc_table(self, result: CommissionRunResult) -> None:
        self._doc_table.set_data(
            [
                {
                    "Beleg": item.document_number,
                    "Datum": item.document_date,
                    "Typ": item.document_type,
                    "SKU": item.sku,
                    "Menge": f"{format_quantity(item.signed_quantity)} Stk.",
                    "Netto": format_euro_amount(item.signed_net),
                    "Regel": item.rule,
                    "__align__Menge": "right",
                    "__align__Netto": "right",
                    "__sort__Menge": item.signed_quantity,
                    "__sort__Netto": item.signed_net,
                }
                for item in result.document_rows
            ]
        )

    def _populate_anomaly_table(self, result: CommissionRunResult) -> None:
        show = self._show_anomalies.isChecked()
        self._anomaly_label.setVisible(show)
        self._anomaly_table.setVisible(show)
        if not show:
            return

        self._anomaly_table.set_data([{"Hinweis": warning} for warning in result.anomalies])

    # ------------------------------------------------------------------
    # Legacy page: article list with computed royalties
    # ------------------------------------------------------------------

    def _build_articles_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self._art_status = QLabel("Artikelliste laden...")
        bar.addWidget(self._art_status)
        bar.addStretch()
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.clicked.connect(self._load_articles)
        bar.addWidget(refresh_btn)
        lay.addLayout(bar)

        self._art_table = DataTable(_ARTICLE_HEADERS)
        self._art_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._art_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._art_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._art_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self._art_table)

        info = QLabel(
            "Artikelliste in DB: Einstellungen > Schluessel-Verwaltung > calculation.articles (JSON-Array)."
        )
        info.setObjectName("infoLabel")
        info.setWordWrap(True)
        lay.addWidget(info)
        return page

    def _load_articles(self) -> None:
        svc: CalculationService = self._container.resolve(CalculationService)

        def job() -> list[ArticleEntry]:
            return svc.load_articles()

        self._worker = BackgroundWorker(job)
        self._worker.signals.result.connect(self._on_articles_loaded)
        self._worker.signals.error.connect(self._on_error)
        self._worker.start()

    def _on_articles_loaded(self, rows: object) -> None:
        if not isinstance(rows, list):
            return
        self._articles = rows  # type: ignore[assignment]
        if not self._articles:
            self._art_status.setText(
                "Keine Artikel — bitte calculation.articles in Einstellungen befuellen."
            )
        else:
            self._art_status.setText(f"{len(self._articles)} Artikel geladen")
        self._populate_articles(self._articles)

    def _populate_articles(self, items: list[ArticleEntry]) -> None:
        payload: list[dict[str, object]] = []
        for art in items:
            res = calculate_royalty(
                art.gross_price, vat_pct=art.vat_pct, royalty_pct=art.royalty_pct
            )
            payload.append(
                {
                    "Titel": art.title,
                    "Brutto EUR": f"{art.gross_price:.2f}",
                    "MwSt %": f"{art.vat_pct:.1f}",
                    "Provision %": f"{art.royalty_pct:.1f}",
                    "Netto EUR": f"{res.net:.2f}",
                    "MwSt EUR": f"{res.vat_amount:.2f}",
                    "Provision EUR": f"{res.royalty_amount:.2f}",
                    "Notiz": art.note,
                    "__align__Brutto EUR": "right",
                    "__align__MwSt %": "center",
                    "__align__Provision %": "center",
                    "__align__Netto EUR": "right",
                    "__align__MwSt EUR": "right",
                    "__align__Provision EUR": "right",
                }
            )
        self._art_table.set_data(payload)

    # ------------------------------------------------------------------
    # Legacy page: quick calculator
    # ------------------------------------------------------------------

    def _build_calc_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        grp = QGroupBox("Eingabe")
        form = QFormLayout(grp)

        self._calc_gross = QDoubleSpinBox()
        self._calc_gross.setRange(0.0, 99999.99)
        self._calc_gross.setDecimals(2)
        self._calc_gross.setSuffix(" EUR")
        self._calc_gross.setValue(10.00)
        form.addRow("Bruttopreis:", self._calc_gross)

        self._calc_vat = QDoubleSpinBox()
        self._calc_vat.setRange(0.0, 100.0)
        self._calc_vat.setDecimals(1)
        self._calc_vat.setSuffix(" %")
        self._calc_vat.setValue(10.0)
        form.addRow("MwSt-Satz:", self._calc_vat)

        self._calc_royalty = QDoubleSpinBox()
        self._calc_royalty.setRange(0.0, 100.0)
        self._calc_royalty.setDecimals(2)
        self._calc_royalty.setSuffix(" %")
        self._calc_royalty.setValue(0.0)
        form.addRow("Provisionssatz (auf Netto):", self._calc_royalty)

        lay.addWidget(grp)

        calc_btn = QPushButton("Berechnen")
        calc_btn.clicked.connect(self._run_calc)
        lay.addWidget(calc_btn)

        res_grp = QGroupBox("Ergebnis")
        res_lay = QFormLayout(res_grp)

        self._res_net = QLabel("—")
        res_lay.addRow("Nettobetrag:", self._res_net)
        self._res_vat = QLabel("—")
        res_lay.addRow("MwSt-Betrag:", self._res_vat)
        self._res_provision = QLabel("—")
        res_lay.addRow("Provision:", self._res_provision)
        self._res_net_after = QLabel("—")
        res_lay.addRow("Netto nach Provision:", self._res_net_after)
        lay.addWidget(res_grp)

        lay.addStretch()
        return page

    def _run_calc(self) -> None:
        gross = self._calc_gross.value()
        vat = self._calc_vat.value()
        prov = self._calc_royalty.value()
        res = calculate_royalty(gross, vat_pct=vat, royalty_pct=prov)
        self._res_net.setText(f"{res.net:.4f} EUR")
        self._res_vat.setText(f"{res.vat_amount:.4f} EUR")
        self._res_provision.setText(f"{res.royalty_amount:.4f} EUR")
        self._res_net_after.setText(f"{res.net_after_royalty:.4f} EUR")

    def _on_error(self, exc: BaseException) -> None:
        logger.exception("CalculationView error: %s", exc)
        QMessageBox.critical(self, "Fehler", str(exc))
