from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.plc_shipment import PlcShipmentRepository
from xw_office.ui.modules.rechnungen.plc_evidence_dialog import PlcEvidenceDialog


def test_evidence_dialog_confirms_scanned_code_for_specific_package(qtbot: object) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repo = PlcShipmentRepository(sessionmaker(bind=engine, expire_on_commit=False))
    key = "3" * 64
    repo.reserve(
        request_key=key, invoice_id="invoice-5", reference="20860",
        invoice_number="RE-5", mode="TEST", transport="webservice",
        product_code="10", country_iso2="AT",
        parcel_snapshots=(
            {"reference": "20860-P1", "weight_kg": "0.5", "contents": [
                {"quantity": 2, "name": "Alpenmarsch", "sku": "XW-400"}
            ]},
            {"reference": "20860-P2", "weight_kg": "0.5", "contents": [
                {"quantity": 1, "name": "Bergklang", "sku": "XW-401"}
            ]},
        ),
    )
    repo.mark_created(key, tracking_codes=("CODE-1", "CODE-2"), label_sha256="4" * 64)
    dialog = PlcEvidenceDialog(repo, invoice_id="invoice-5")
    qtbot.addWidget(dialog)
    assert "Alpenmarsch" in dialog._details.toPlainText()  # noqa: SLF001
    assert dialog._package.count() == 2  # noqa: SLF001
    dialog._package.setCurrentIndex(1)  # noqa: SLF001
    dialog._code.setText("CODE-2")  # noqa: SLF001
    dialog._confirm.click()  # noqa: SLF001
    evidence = repo.list_parcel_evidence(invoice_id="invoice-5")
    assert [entry.tracking_code for entry in evidence] == ["", "CODE-2"]
    assert "CODE-2" in dialog._details.toPlainText()  # noqa: SLF001
