"""Unit coverage for persistent PLC label PDF recovery."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.plc.models import PlcParcel, PlcShipmentDraft
from xw_office.services.plc.polling import ShipmentAddress
from xw_office.services.printing.print_jobs import PdfPrintJob
from xw_office.services.printing.print_queue import PrintQueueService
from xw_office.services.secrets.service import SecretService
from xw_office.ui.modules.rechnungen.plc_label_dialog import PlcLabelPrintDialog


CUSTOMS_SAMPLE = Path("resources/api_specs/plc/Zollerklaerung_TEST.pdf")


def _shipment(*, reference: str = "20868", invoice_number: str = "RE-261952") -> PlcShipmentDraft:
    return PlcShipmentDraft(
        reference=reference,
        invoice_id="127129418",
        invoice_number=invoice_number,
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
        parcels=(PlcParcel(weight_kg=0.5, reference=reference),),
    )


def test_archive_keeps_the_exact_plc_pdf_under_order_and_invoice_number(tmp_path) -> None:
    archive = PlcLabelArchive(tmp_path)
    pdf = b"%PDF-1.7\nPLC label"

    path = archive.save(_shipment(), pdf)

    assert path == tmp_path / "20868 - RE-261952.pdf"
    assert path.read_bytes() == pdf
    assert archive.find(_shipment()) == path


def test_archive_uses_windows_safe_filename_parts(tmp_path) -> None:
    archive = PlcLabelArchive(tmp_path)

    path = archive.save(
        _shipment(reference="20868/1", invoice_number="RE:261952"), b"%PDF-1.7\nPLC label"
    )

    assert path.name == "20868-1 - RE-261952.pdf"


def test_archive_rejects_non_pdf_response(tmp_path) -> None:
    with pytest.raises(ValueError, match="PDF"):
        PlcLabelArchive(tmp_path).save(_shipment(), b"not a PDF")


def test_archive_keeps_customs_form_separate_from_label_lookup(tmp_path) -> None:
    archive = PlcLabelArchive(tmp_path)
    shipment = _shipment()

    path = archive.save_customs_document(shipment, b"%PDF-1.7\nCN23")

    assert path == tmp_path / "customs" / "20868 - RE-261952 - Zollformular.pdf"
    assert archive.find_customs_document(shipment) == path
    assert archive.find(shipment) is None


def test_archive_keeps_original_and_calibrated_customs_print_pdf(tmp_path) -> None:
    archive = PlcLabelArchive(tmp_path)
    shipment = _shipment()
    original_bytes = CUSTOMS_SAMPLE.read_bytes()
    original = archive.save_customs_document(shipment, original_bytes)

    print_ready = archive.ensure_customs_print_document(shipment)

    assert original.read_bytes() == original_bytes
    assert print_ready == tmp_path / "customs" / "print_ready" / (
        "20868 - RE-261952 - Zollformular - A5.pdf"
    )
    assert archive.find_customs_print_document(shipment) == print_ready


def test_customs_archive_lookup_finds_newest_suffixed_shipment(tmp_path) -> None:
    archive = PlcLabelArchive(tmp_path)
    original = _shipment()
    second = _shipment(reference="20868-2", invoice_number="RE-261952-2")
    archive.save_customs_document(original, b"%PDF-1.7\nCN23 original")
    second_path = archive.save_customs_document(second, b"%PDF-1.7\nCN23 second")

    found = archive.find_customs_for_invoice(
        order_reference="20868",
        invoice_number="RE-261952",
    )

    assert found == second_path


def test_additional_plc_label_uses_suffix_for_order_and_invoice(tmp_path) -> None:
    dialog = PlcLabelPrintDialog.__new__(PlcLabelPrintDialog)
    dialog._label_archive = PlcLabelArchive(tmp_path)  # noqa: SLF001
    original = _shipment()
    dialog._label_archive.save(original, b"%PDF-1.7\nPLC label")  # noqa: SLF001

    second = dialog._next_additional_shipment(original)  # noqa: SLF001

    assert second.reference == "20868-2"
    assert second.invoice_number == "RE-261952-2"
    assert second.parcels[0].reference == "20868-2"

    dialog._label_archive.save(second, b"%PDF-1.7\nPLC label")  # noqa: SLF001
    third = dialog._next_additional_shipment(original)  # noqa: SLF001

    assert third.reference == "20868-3"
    assert third.invoice_number == "RE-261952-3"


def test_webservice_label_queue_uses_explicit_a5_layout(tmp_path) -> None:
    pdf_path = tmp_path / "label.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\nPLC label")
    queued: list[PdfPrintJob] = []

    class QueueStub:
        def enqueue(self, job: PdfPrintJob) -> str:
            queued.append(job)
            return job.id

    class PrintingStub:
        def resolve_profile(self, _profile_id: str) -> None:
            return None

    class ConfigStub:
        printing = PrintingStub()

    class ContainerStub:
        config = ConfigStub()

        def resolve(self, cls: object) -> object:
            if cls is SecretService:
                return SimpleNamespace(get_secret=lambda _key: "Paketmarke A5")
            assert cls is PrintQueueService
            return QueueStub()

    dialog = PlcLabelPrintDialog.__new__(PlcLabelPrintDialog)
    dialog._container = ContainerStub()  # noqa: SLF001

    dialog._queue_webservice_label(pdf_path, "20868")  # noqa: SLF001

    assert len(queued) == 1
    assert queued[0].page_size == "A5"
    assert queued[0].orientation == "portrait"
    assert queued[0].placement_mode == "printable_origin"
    assert queued[0].scale_mode == "none"
    assert queued[0].alignment == "center"


def test_customs_document_queue_uses_af_pdf_on_dedicated_100_percent_queue(tmp_path) -> None:
    pdf_path = tmp_path / "cn23.pdf"
    pdf_path.write_bytes(CUSTOMS_SAMPLE.read_bytes())
    queued: list[PdfPrintJob] = []

    class QueueStub:
        def enqueue(self, job: PdfPrintJob) -> str:
            queued.append(job)
            return job.id

    profile = SimpleNamespace(
        printer_name="Zollformular XW 100",
        page_size="A5",
        orientation="portrait",
        placement_mode="paper_origin",
        scale_mode="fit",
        scale_percent=100.0,
        alignment="top_left",
        dpi=None,
        x_offset_mm=0.0,
        y_offset_mm=0.0,
    )

    class PrintingStub:
        def resolve_profile(self, profile_id: str) -> object:
            assert profile_id == "plc_customs"
            return profile

    class ConfigStub:
        printing = PrintingStub()

    class ContainerStub:
        config = ConfigStub()

        def resolve(self, _cls: object) -> object:
            return QueueStub()

    dialog = PlcLabelPrintDialog.__new__(PlcLabelPrintDialog)
    dialog._container = ContainerStub()  # noqa: SLF001

    dialog._queue_customs_document(pdf_path, "20868")  # noqa: SLF001

    assert len(queued) == 1
    assert queued[0].printer_name == "Zollformular XW 100"
    assert Path(queued[0].pdf_path).parent.name == "print_ready"
    assert queued[0].page_size == "A5"
    assert queued[0].placement_mode == "paper_origin"
    assert queued[0].scale_mode == "fit"
    assert queued[0].scale_percent == pytest.approx(100.0)
    assert queued[0].alignment == "top_left"
