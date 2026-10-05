"""Success and error feedback behavior for the PLC label dialog."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import QDialog, QHeaderView, QLabel, QMessageBox

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.core.signals import AppSignals
from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.plc.models import PlcCustomsArticle, PlcParcel, PlcShipmentDraft
from xw_office.services.plc.packing_list import PackingListService
from xw_office.services.plc.partial_fulfillment import PartialFulfillmentStore
from xw_office.services.plc.polling import ShipmentAddress
from xw_office.services.plc.service import PlcShipmentService
from xw_office.services.plc.webservice import PlcWebserviceResult
from xw_office.services.wix.client import WixOrderItem
from xw_office.ui.modules.rechnungen import plc_label_dialog as plc_dialog_module
from xw_office.ui.modules.rechnungen.plc_label_dialog import (
    PlcLabelPrintDialog,
    _PlcSendResult,
)


CUSTOMS_SAMPLE = Path("resources/api_specs/plc/Zollerklaerung_TEST.pdf")


def _container() -> Container:
    container = Container(AppConfig())
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    return container


def _shipment() -> PlcShipmentDraft:
    return PlcShipmentDraft(
        reference="20868",
        invoice_id="127129418",
        invoice_number="RE-261952",
        mode="TEST",
        product_id="10",
        recipient=ShipmentAddress(
            name1="Max Mustermann",
            street="Teststrasse",
            house_no="1",
            zip="1030",
            city="Wien",
            country_iso2="AT",
        ),
        parcels=(PlcParcel(weight_kg=0.5, reference="20868"),),
    )


def _customs_shipment() -> PlcShipmentDraft:
    shipment = _shipment()
    return replace(
        shipment,
        recipient=replace(shipment.recipient, country_iso2="CH"),
        customs_description="Printed sheet music books",
        articles=(
            PlcCustomsArticle(
                sku="XW-400",
                name="Printed sheet music book – Alpenmarsch",
                quantity=1,
                net_weight_kg=0.4,
                customs_value_eur=19.9,
            ),
        ),
    )


def test_success_overlay_shows_green_check_and_auto_closes(
    qtbot: object,
    monkeypatch: object,
) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog.show()
    monkeypatch.setattr(plc_dialog_module, "_SUCCESS_OVERLAY_MS", 20)

    dialog._show_success_overlay("PLC-Label erstellt")  # noqa: SLF001

    overlay = dialog._success_overlay  # noqa: SLF001
    assert overlay is not None
    assert overlay.isVisible()
    assert "#16a34a" in overlay.styleSheet()
    check = overlay.findChild(QLabel, "plcSuccessCheck")
    assert check is not None
    assert check.text() == "✓"
    qtbot.waitUntil(
        lambda: dialog.result() == int(QDialog.DialogCode.Accepted),
        timeout=1000,
    )


def test_successful_webservice_result_uses_overlay_without_information_popup(
    qtbot: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    class PlcServiceStub:
        def __init__(self) -> None:
            self.marked_jobs: list[str] = []

        def mark_print_queued(self, _shipment: PlcShipmentDraft, job_id: str) -> None:
            self.marked_jobs.append(job_id)

    plc_service = PlcServiceStub()
    container = _container()
    container.register(PlcShipmentService, lambda _: plc_service)  # type: ignore[arg-type,return-value]
    dialog = PlcLabelPrintDialog(container, None)
    qtbot.addWidget(dialog)
    dialog._label_archive = PlcLabelArchive(tmp_path)  # noqa: SLF001
    dialog._queue_webservice_label = lambda _path, _reference: "print-job-1"  # type: ignore[method-assign]  # noqa: SLF001
    shown: list[str] = []
    dialog._show_success_overlay = shown.append  # type: ignore[method-assign]  # noqa: SLF001

    def fail_information(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Erfolg darf kein modales Informationsfenster öffnen")

    monkeypatch.setattr(QMessageBox, "information", fail_information)
    dialog._on_send_result(  # noqa: SLF001
        _shipment(),
        _PlcSendResult(
            transport="webservice",
            reference="20868",
            webservice_result=PlcWebserviceResult(
                pdf_bytes=b"%PDF-1.7\nPLC label",
                tracking_codes=("TRACK-1",),
            ),
        ),
    )

    assert shown == ["PLC-Label erstellt"]
    assert plc_service.marked_jobs == ["print-job-1"]


def test_customs_result_archives_both_pdfs_before_first_print_job(
    qtbot: object,
    tmp_path: Path,
) -> None:
    class PlcServiceStub:
        def mark_print_queued(self, _shipment: PlcShipmentDraft, _job_id: str) -> None:
            return

    container = _container()
    container.register(PlcShipmentService, lambda _: PlcServiceStub())  # type: ignore[arg-type,return-value]
    dialog = PlcLabelPrintDialog(container, None)
    qtbot.addWidget(dialog)
    dialog._label_archive = PlcLabelArchive(tmp_path)  # noqa: SLF001
    shipment = _customs_shipment()
    queue_order: list[str] = []

    def queue_label(_path: object, _reference: str) -> str:
        assert dialog._label_archive.find(shipment) is not None  # noqa: SLF001
        assert dialog._label_archive.find_customs_document(shipment) is not None  # noqa: SLF001
        assert dialog._label_archive.find_customs_print_document(shipment) is not None  # noqa: SLF001
        queue_order.append("label")
        return "label-job"

    def queue_customs(print_path: object, _reference: str) -> str:
        assert dialog._label_archive.find(shipment) is not None  # noqa: SLF001
        assert dialog._label_archive.find_customs_document(shipment) is not None  # noqa: SLF001
        assert Path(str(print_path)).parent.name == "print_ready"
        queue_order.append("customs")
        return "customs-job"

    dialog._queue_webservice_label = queue_label  # type: ignore[method-assign]  # noqa: SLF001
    dialog._queue_customs_document = queue_customs  # type: ignore[method-assign]  # noqa: SLF001
    dialog._show_success_overlay = lambda _message: None  # type: ignore[method-assign]  # noqa: SLF001

    dialog._on_send_result(  # noqa: SLF001
        shipment,
        _PlcSendResult(
            transport="webservice",
            reference=shipment.reference,
            webservice_result=PlcWebserviceResult(
                pdf_bytes=b"%PDF-1.7\nPLC label",
                tracking_codes=(),
                shipment_documents=CUSTOMS_SAMPLE.read_bytes(),
            ),
        ),
    )

    assert queue_order == ["label", "customs"]


def test_customs_result_keeps_both_archives_when_first_print_queue_fails(
    qtbot: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._label_archive = PlcLabelArchive(tmp_path)  # noqa: SLF001
    shipment = _customs_shipment()
    warnings: list[str] = []

    def fail_queue(_path: object, _reference: str) -> str:
        raise RuntimeError("Drucker offline")

    dialog._queue_webservice_label = fail_queue  # type: ignore[method-assign]  # noqa: SLF001
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(str(message)),
    )

    dialog._on_send_result(  # noqa: SLF001
        shipment,
        _PlcSendResult(
            transport="webservice",
            reference=shipment.reference,
            webservice_result=PlcWebserviceResult(
                pdf_bytes=b"%PDF-1.7\nPLC label",
                tracking_codes=(),
                shipment_documents=CUSTOMS_SAMPLE.read_bytes(),
            ),
        ),
    )

    assert dialog._label_archive.find(shipment) is not None  # noqa: SLF001
    assert dialog._label_archive.find_customs_document(shipment) is not None  # noqa: SLF001
    assert dialog._label_archive.find_customs_print_document(shipment) is not None  # noqa: SLF001
    assert warnings and "Lokal archiviert" in warnings[0]


def test_send_error_remains_modal_and_keeps_plc_dialog_open(
    qtbot: object,
    monkeypatch: object,
) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog.show()
    critical_calls: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, _title, message: critical_calls.append(str(message)),
    )

    dialog._on_send_error(_shipment(), RuntimeError("PLC nicht erreichbar"))  # noqa: SLF001

    assert critical_calls == ["PLC nicht erreichbar"]
    assert dialog.isVisible()
    assert dialog.result() != int(QDialog.DialogCode.Accepted)


def test_customs_table_uses_only_physical_wix_items_and_builds_cn23_values(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._weight_edit.setText("0,65")  # noqa: SLF001

    dialog._populate_customs_table(  # noqa: SLF001
        [
            WixOrderItem(
                sku="XW-400",
                name="Alpenmarsch",
                qty=2,
                unit_weight_kg=0.25,
                unit_price_gross=19.9,
                currency="EUR",
            ),
            WixOrderItem(name="PDF Download", qty=1, unit_price_gross=9.9, is_digital=True),
        ]
    )

    articles = dialog._build_customs_articles()  # noqa: SLF001
    assert len(articles) == 1
    assert articles[0].name == "Printed sheet music book - Alpenmarsch"
    assert articles[0].quantity == 2
    assert articles[0].net_weight_kg == 0.25
    assert articles[0].customs_value_eur == 19.9
    assert articles[0].origin_iso2 == "AT"
    assert articles[0].hs_tariff_number == "49040000"
    assert "2 Stk." in dialog._customs_summary.text()  # noqa: SLF001
    assert "39.80 EUR" in dialog._customs_summary.text()  # noqa: SLF001
    assert "Paket-Brutto 0.650 kg" in dialog._customs_summary.text()  # noqa: SLF001
    assert "Verpackung/Differenz 0.150 kg" in dialog._customs_summary.text()  # noqa: SLF001
    assert dialog._customs_details.isHidden()  # noqa: SLF001

    dialog._customs_details_btn.click()  # noqa: SLF001
    assert not dialog._customs_details.isHidden()  # noqa: SLF001

    dialog._customs_table.item(0, 3).setText("0,200")  # noqa: SLF001
    edited = dialog._build_customs_articles()  # noqa: SLF001
    assert edited[0].net_weight_kg == 0.2
    assert "Verpackung/Differenz 0.250 kg" in dialog._customs_summary.text()  # noqa: SLF001


def test_multiple_parcels_split_physical_items_and_prepare_two_packing_lists(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [  # noqa: SLF001
        WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=2),
        WixOrderItem(sku="XW-PDF", name="Download", qty=1, is_digital=True),
    ]
    dialog._package_count.setValue(2)  # noqa: SLF001

    assert dialog._packing_table.rowCount() == 2  # noqa: SLF001
    assert dialog._packing_table.item(1, 2).text() == "2"  # noqa: SLF001
    assert dialog._packing_table.item(1, 3).text() == "0"  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("1")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("0,31")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("0,29")  # noqa: SLF001

    parcels, packing_lists = dialog._build_parcels_and_packing_lists(  # noqa: SLF001
        reference="21104",
        package_type="PC",
    )

    assert [parcel.weight_kg for parcel in parcels] == [0.31, 0.29]
    assert [item.quantity for item in packing_lists[0].items] == [1]
    assert [item.quantity for item in packing_lists[1].items] == [1]
    assert all("Download" not in item.name for packing_list in packing_lists for item in packing_list.items)


def test_multiple_parcel_weights_are_used_instead_of_total_weight(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=2)]  # noqa: SLF001
    dialog._package_count.setValue(2)  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("1")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("11,69")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("10,21")  # noqa: SLF001

    parcels, packing_lists = dialog._build_parcels_and_packing_lists(  # noqa: SLF001
        reference="21104",
        package_type="PC",
    )

    assert [parcel.weight_kg for parcel in parcels] == [11.69, 10.21]
    assert [packing_list.weight_kg for packing_list in packing_lists] == [11.69, 10.21]
    assert dialog._weight_edit.text() == "21,90"  # noqa: SLF001


def test_partial_allocation_can_produce_packlists_and_next_label_shows_open_quantity(
    qtbot: object,
    tmp_path: Path,
) -> None:
    store = PartialFulfillmentStore(tmp_path / "partial.json")
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._partial_fulfillments = store  # noqa: SLF001
    dialog._primary_order_number.setText("21104")  # noqa: SLF001
    dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=10)]  # noqa: SLF001
    dialog._package_count.setValue(2)  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("4")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("0")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("1,0")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("1,0")  # noqa: SLF001

    _parcels, packing_lists = dialog._build_parcels_and_packing_lists(  # noqa: SLF001
        reference="21104",
        package_type="PC",
        allow_partial=True,
    )
    order_key, sent_quantities = dialog._capture_pending_fulfillment()  # noqa: SLF001
    store.add_dispatched_quantities(order_key, sent_quantities)

    assert [item.quantity for item in packing_lists[0].items] == [4]
    assert not packing_lists[1].items
    assert "offen 10" in dialog._last_allocation_warnings[0]  # noqa: SLF001

    next_dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(next_dialog)
    next_dialog._partial_fulfillments = store  # noqa: SLF001
    next_dialog._primary_order_number.setText("21104")  # noqa: SLF001
    next_dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=10)]  # noqa: SLF001
    next_dialog._packing_open_quantities = next_dialog._open_quantities_for_items(next_dialog._packing_items)  # noqa: SLF001
    next_dialog._package_count.setValue(2)  # noqa: SLF001

    assert next_dialog._packing_table.item(1, 1).text() == "10 / offen 6"  # noqa: SLF001
    assert next_dialog._packing_table.item(1, 2).text() == "6"  # noqa: SLF001


def test_multiple_parcel_price_sums_individual_tariffs_and_shows_contents(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._country_combo.setEditText("Austria")  # noqa: SLF001
    dialog._packing_items = [  # noqa: SLF001
        WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=10),
        WixOrderItem(sku="XW-401", name="Partitur", qty=2),
    ]
    dialog._package_count.setValue(2)  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("10+1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("0")  # noqa: SLF001
    dialog._packing_table.item(2, 2).setText("0")  # noqa: SLF001
    dialog._packing_table.item(2, 3).setText("2")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("2,01")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("8")  # noqa: SLF001

    assert dialog._weight_edit.isReadOnly()  # noqa: SLF001
    assert dialog._weight_edit.text() == "10,01"  # noqa: SLF001
    assert dialog._price_label.text() == "Preis: 13,60 € (2 Pakete)"  # noqa: SLF001
    assert "Paket 1: 2,01 kg · 6.39 €" in dialog._price_label.toolTip()  # noqa: SLF001
    assert dialog._parcel_weight_edits[0].maximumWidth() == 105  # noqa: SLF001
    assert dialog._parcel_contents_labels[0].text() == "10+1 × Alpenmarsch"  # noqa: SLF001
    assert dialog._parcel_contents_labels[1].text() == "2 × Partitur"  # noqa: SLF001


def test_packlist_print_button_uses_current_parcel_contexts(
    qtbot: object,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=2)]  # noqa: SLF001
    dialog._package_count.setValue(2)  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("1")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("11,69")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("10,21")  # noqa: SLF001
    printed_contexts: list[object] = []

    def generate_pdf(_self: object, contexts: object, *, output_dir: Path) -> Path:
        printed_contexts.extend(contexts)
        assert output_dir.name == "packlists"
        return tmp_path / "packlists.pdf"

    monkeypatch.setattr(PackingListService, "generate_pdf", generate_pdf)
    monkeypatch.setattr(plc_dialog_module, "queue_packing_lists", lambda *_args: "print-job-123")

    dialog._print_packing_lists()  # noqa: SLF001

    assert dialog._packing_print_btn.text() == "Packliste drucken"  # noqa: SLF001
    assert [context.weight_kg for context in printed_contexts] == [11.69, 10.21]
    assert "Druckauftrag print-jo" in dialog._status.text()  # noqa: SLF001


def test_weight_distribution_keeps_duplicate_skus_together_and_adds_parcels(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [  # noqa: SLF001
        WixOrderItem(sku="XW-SAME", name="Gleicher Artikel", qty=8, unit_weight_kg=0.5),
        WixOrderItem(sku="XW-SAME", name="Gleicher Artikel", qty=8, unit_weight_kg=0.5),
        WixOrderItem(sku="XW-OTHER", name="Anderer Artikel", qty=8, unit_weight_kg=0.7),
    ]
    dialog._package_count.setValue(2)  # noqa: SLF001

    dialog._auto_distribute_by_weight()  # noqa: SLF001

    assert dialog._package_count.value() == 2  # noqa: SLF001
    assert dialog._packing_table.item(1, 2).text() == "8"  # noqa: SLF001
    assert dialog._packing_table.item(2, 2).text() == "8"  # noqa: SLF001
    assert dialog._packing_table.item(3, 3).text() == "8"  # noqa: SLF001
    assert [edit.text() for edit in dialog._parcel_weight_edits] == ["8,80", "6,40"]  # noqa: SLF001
    assert "800 g Reserve" in dialog._status.text()  # noqa: SLF001


def test_weight_distribution_expands_to_additional_safe_parcel(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [  # noqa: SLF001
        WixOrderItem(sku="XW-1", name="Produkt 1", qty=10, unit_weight_kg=0.6),
        WixOrderItem(sku="XW-2", name="Produkt 2", qty=10, unit_weight_kg=0.6),
        WixOrderItem(sku="XW-3", name="Produkt 3", qty=10, unit_weight_kg=0.6),
    ]
    dialog._package_count.setValue(2)  # noqa: SLF001

    dialog._auto_distribute_by_weight()  # noqa: SLF001

    assert dialog._package_count.value() == 3  # noqa: SLF001
    assert [edit.text() for edit in dialog._parcel_weight_edits] == ["6,80", "6,80", "6,80"]  # noqa: SLF001
    assert all(
        sum(int(dialog._packing_table.item(row, 2 + parcel).text()) for row in range(1, 4)) == 10  # noqa: SLF001
        for parcel in range(3)
    )


def test_parcel_controls_add_clear_delete_and_keep_columns_resizable(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=4)]  # noqa: SLF001
    dialog._package_count.setValue(2)  # noqa: SLF001

    header = dialog._packing_table.horizontalHeader()  # noqa: SLF001
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Interactive
    assert dialog._packing_table.cellWidget(0, 2) is not None  # noqa: SLF001
    assert dialog._packing_table.cellWidget(0, 4) is not None  # noqa: SLF001

    dialog._add_parcel()  # noqa: SLF001
    assert dialog._package_count.value() == 3  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("2")  # noqa: SLF001
    dialog._packing_table.item(1, 4).setText("1")  # noqa: SLF001
    dialog._clear_package(1)  # noqa: SLF001
    assert dialog._packing_table.item(1, 3).text() == "0"  # noqa: SLF001

    dialog._packing_table.item(1, 3).setText("2")  # noqa: SLF001
    dialog._delete_parcel(1)  # noqa: SLF001
    assert dialog._package_count.value() == 2  # noqa: SLF001
    assert dialog._packing_table.item(1, 2).text() == "3"  # noqa: SLF001
    assert dialog._packing_table.item(1, 3).text() == "1"  # noqa: SLF001


def test_b2b_bonus_quantity_is_printed_but_not_counted_as_ordered(qtbot: object) -> None:
    summary = plc_dialog_module.InvoiceSummary(id="b2b", order_reference="12345")
    dialog = PlcLabelPrintDialog(_container(), summary)
    qtbot.addWidget(dialog)
    dialog._packing_items = [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=20)]  # noqa: SLF001
    dialog._package_count.setValue(2)  # noqa: SLF001
    dialog._packing_table.item(1, 2).setText("10+1")  # noqa: SLF001
    dialog._packing_table.item(1, 3).setText("10+1")  # noqa: SLF001
    dialog._parcel_weight_edits[0].setText("1,0")  # noqa: SLF001
    dialog._parcel_weight_edits[1].setText("1,0")  # noqa: SLF001

    _parcels, packing_lists = dialog._build_parcels_and_packing_lists(  # noqa: SLF001
        reference="12345",
        package_type="PC",
    )

    assert [item.quantity for item in packing_lists[0].items] == [11]
    assert [item.quantity for item in packing_lists[1].items] == [11]


def test_incomplete_wix_customs_weight_expands_details_automatically(qtbot: object) -> None:
    dialog = PlcLabelPrintDialog(_container(), None)
    qtbot.addWidget(dialog)
    dialog._weight_edit.setText("0,50")  # noqa: SLF001

    dialog._populate_customs_table(  # noqa: SLF001
        [WixOrderItem(sku="XW-400", name="Alpenmarsch", qty=1, unit_price_gross=19.9)]
    )

    assert not dialog._customs_details.isHidden()  # noqa: SLF001
    assert "unvollständig" in dialog._customs_summary.text()  # noqa: SLF001
