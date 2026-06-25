"""Unit coverage for persistent PLC label PDF recovery."""
from __future__ import annotations

import pytest

from xw_studio.services.plc.label_archive import PlcLabelArchive
from xw_studio.services.plc.models import PlcParcel, PlcShipmentDraft
from xw_studio.services.plc.polling import ShipmentAddress


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

    path = archive.save(_shipment(reference="20868/1", invoice_number="RE:261952"), b"%PDF-1.7\nPLC label")

    assert path.name == "20868-1 - RE-261952.pdf"


def test_archive_rejects_non_pdf_response(tmp_path) -> None:
    with pytest.raises(ValueError, match="PDF"):
        PlcLabelArchive(tmp_path).save(_shipment(), b"not a PDF")
