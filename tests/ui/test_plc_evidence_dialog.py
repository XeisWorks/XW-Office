from __future__ import annotations

from datetime import datetime, timezone
from threading import Event

from PySide6.QtCore import QTimer
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from xw_office.models.base import Base
from xw_office.repositories.plc_shipment import PlcParcelEvidence, PlcShipmentRepository
from xw_office.ui.modules.rechnungen.plc_evidence_dialog import PlcEvidenceDialog


def test_evidence_dialog_confirms_scanned_code_for_specific_package(qtbot: object) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    qtbot.waitUntil(lambda: "Alpenmarsch" in dialog._details.toPlainText(), timeout=3000)  # noqa: SLF001
    assert "Alpenmarsch" in dialog._details.toPlainText()  # noqa: SLF001
    assert dialog._package.count() == 2  # noqa: SLF001
    dialog._package.setCurrentIndex(1)  # noqa: SLF001
    dialog._code.setText("CODE-2")  # noqa: SLF001
    dialog._confirm.click()  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=3000)  # noqa: SLF001
    qtbot.waitUntil(lambda: "CODE-2" in dialog._details.toPlainText(), timeout=3000)  # noqa: SLF001
    evidence = repo.list_parcel_evidence(invoice_id="invoice-5")
    assert [entry.tracking_code for entry in evidence] == ["", "CODE-2"]
    assert "CODE-2" in dialog._details.toPlainText()  # noqa: SLF001
    raw = b"""<TrackingData><TrackingEvents>
      <Header><TrackingVersion>2</TrackingVersion><EventCount>2</EventCount></Header>
      <Event><ParcelEventId>1</ParcelEventId><IdentCode>CODE-2</IdentCode>
        <EventTimestamp>2026-11-10T10:00:00</EventTimestamp><ParcelEventTypeCode>ANA</ParcelEventTypeCode>
      </Event>
      <Event><ParcelEventId>2</ParcelEventId><IdentCode>CODE-2</IdentCode>
        <EventTimestamp>2026-11-11T11:00:00</EventTimestamp><ParcelEventTypeCode>ZUS</ParcelEventTypeCode>
      </Event>
    </TrackingEvents></TrackingData>"""
    assert repo.import_post_tracking_xml(raw, invoice_id="invoice-5") == 2
    dialog._reload()  # noqa: SLF001
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=3000)  # noqa: SLF001
    details = dialog._details.toPlainText()  # noqa: SLF001
    assert "Post-Annahme: 10.11.2026 10:00" in details
    assert "Zustellung: 11.11.2026 11:00" in details


def _entry() -> PlcParcelEvidence:
    return PlcParcelEvidence(
        shipment_id="shipment-1",
        reference="PLC-1",
        status="created",
        created_at=datetime.now(timezone.utc),
        package_number=1,
        package_count=2,
        weight_kg=None,
        contents=(),
        tracking_code="",
        available_codes=("CODE-1", "CODE-2"),
        code_assignment="",
        confirmed_at=None,
        packing_pdf_sha256="",
    )


class _Repository:
    def __init__(self) -> None:
        self.entered, self.release = Event(), Event()
        self.confirm_calls: list[tuple[str, int, str]] = []
        self.import_calls: list[bytes] = []

    def list_parcel_evidence(self, *, invoice_id: str, invoice_number: str):
        assert (invoice_id, invoice_number) == ("invoice-1", "RE-1")
        return [_entry()]

    def confirm_parcel_code(self, *, shipment_id: str, package_number: int, tracking_code: str) -> bool:
        self.confirm_calls.append((shipment_id, package_number, tracking_code))
        self.entered.set()
        assert self.release.wait(3)
        return True

    def import_post_tracking_xml(self, raw: bytes, *, invoice_id: str, invoice_number: str) -> int:
        assert (invoice_id, invoice_number) == ("invoice-1", "RE-1")
        self.import_calls.append(raw)
        self.entered.set()
        assert self.release.wait(3)
        return 1


def _assert_event_loop_responds(qtbot, entered: Event) -> None:
    qtbot.waitUntil(entered.is_set)
    beats: list[bool] = []
    QTimer.singleShot(20, lambda: beats.append(True))
    qtbot.waitUntil(lambda: bool(beats))


def test_tracking_import_and_code_confirmation_run_in_workers(qtbot, monkeypatch, tmp_path) -> None:
    repository = _Repository()
    dialog = PlcEvidenceDialog(repository, invoice_id="invoice-1", invoice_number="RE-1")  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog._worker is None and dialog._package.count() == 1)  # noqa: SLF001

    dialog._code.setText("CODE-2")  # noqa: SLF001
    dialog._confirm_code()  # noqa: SLF001
    _assert_event_loop_responds(qtbot, repository.entered)
    assert not dialog._confirm.isEnabled()  # noqa: SLF001
    dialog.accept()
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()
    repository.release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=2000)  # noqa: SLF001
    assert repository.confirm_calls == [("shipment-1", 1, "CODE-2")]

    repository.entered.clear()
    repository.release.clear()
    xml_path = tmp_path / "tracking.xml"
    xml_path.write_bytes(b"<tracking />")
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.plc_evidence_dialog.QFileDialog.getOpenFileName",
        lambda *_args: (str(xml_path), ""),
    )
    monkeypatch.setattr(
        "xw_office.ui.modules.rechnungen.plc_evidence_dialog.QMessageBox.information",
        lambda *_args: None,
    )
    dialog._import_tracking()  # noqa: SLF001
    _assert_event_loop_responds(qtbot, repository.entered)
    assert not dialog._import_button.isEnabled()  # noqa: SLF001
    dialog.accept()
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()
    repository.release.set()
    qtbot.waitUntil(lambda: dialog._worker is None, timeout=2000)  # noqa: SLF001
    assert repository.import_calls == [b"<tracking />"]
