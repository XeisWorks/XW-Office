"""Smoke tests for the QR-Code-Serien batch dialog and settings dialog."""
from __future__ import annotations

from PySide6.QtWidgets import QTableWidgetItem

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.services.qr_codes.presets import (
    GERADE_ZAHLEN_EXCEL,
    GESAMTSPIELCHEN,
    JEDE_4_ZAHL,
    UNGERADE_ZAHLEN_EXCEL,
    WHOLE_SCALE,
)
from xw_studio.services.qr_codes.service import QrCodeService
from xw_studio.ui.modules.layout.qr_batch_dialog import QrCodeBatchDialog
from xw_studio.ui.modules.layout.qr_settings_dialog import QrSettingsDialog


def _build_container() -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _c: AppSignals())
    register_default_services(container)
    return container


def test_batch_dialog_defaults_to_whole_scale_with_111_records(qtbot: object) -> None:
    container = _build_container()
    dialog = QrCodeBatchDialog(container)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._refresh_preview()  # noqa: SLF001

    assert dialog._variant_combo.currentData() == WHOLE_SCALE  # noqa: SLF001
    assert len(dialog._current_records) == 111  # noqa: SLF001
    assert dialog._current_records[0].logical_id == "UUU#2-POS/01"  # noqa: SLF001
    assert dialog._current_records[-1].logical_id == "UUU#2-POS/111"  # noqa: SLF001
    assert not dialog._generate_btn.isEnabled()  # noqa: SLF001


def test_batch_dialog_enables_generate_once_output_dir_set(qtbot: object, tmp_path: object) -> None:
    container = _build_container()
    dialog = QrCodeBatchDialog(container)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._output_dir_edit.setText(str(tmp_path))  # noqa: SLF001
    dialog._refresh_preview()  # noqa: SLF001

    assert dialog._generate_btn.isEnabled()  # noqa: SLF001


def test_switching_to_each_variant_produces_expected_record_count(qtbot: object, tmp_path: object) -> None:
    container = _build_container()
    dialog = QrCodeBatchDialog(container)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._output_dir_edit.setText(str(tmp_path))  # noqa: SLF001

    expected_counts = {
        WHOLE_SCALE: 111,
        GESAMTSPIELCHEN: 12,
        UNGERADE_ZAHLEN_EXCEL: 25,
        GERADE_ZAHLEN_EXCEL: 13,
        JEDE_4_ZAHL: 6,
    }
    for key, expected in expected_counts.items():
        index = dialog._variant_combo.findData(key)  # noqa: SLF001
        dialog._variant_combo.setCurrentIndex(index)  # noqa: SLF001
        dialog._refresh_preview()  # noqa: SLF001
        assert len(dialog._current_records) == expected, key  # noqa: SLF001


def test_gesamtspielchen_table_add_row_updates_preview(qtbot: object, tmp_path: object) -> None:
    container = _build_container()
    dialog = QrCodeBatchDialog(container)
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]
    dialog._output_dir_edit.setText(str(tmp_path))  # noqa: SLF001
    index = dialog._variant_combo.findData(GESAMTSPIELCHEN)  # noqa: SLF001
    dialog._variant_combo.setCurrentIndex(index)  # noqa: SLF001
    dialog._refresh_preview()  # noqa: SLF001
    assert len(dialog._current_records) == 12  # noqa: SLF001

    dialog._add_table_row()  # noqa: SLF001
    dialog._table_widget.setItem(12, 1, QTableWidgetItem("Testinstrument"))  # noqa: SLF001
    dialog._table_widget.setItem(12, 2, QTableWidgetItem("test"))  # noqa: SLF001
    dialog._refresh_preview()  # noqa: SLF001

    assert len(dialog._current_records) == 13  # noqa: SLF001
    assert dialog._current_records[-1].logical_id == "13 Testinstrument"  # noqa: SLF001


def test_settings_dialog_saves_updated_width(qtbot: object) -> None:
    container = _build_container()
    service = container.resolve(QrCodeService)
    dialog = QrSettingsDialog(service, service.load_settings())
    qtbot.addWidget(dialog)  # type: ignore[attr-defined]

    dialog._width_spin.setValue(500)  # noqa: SLF001
    dialog._on_save()  # noqa: SLF001

    assert dialog.result_settings().width_px == 500
