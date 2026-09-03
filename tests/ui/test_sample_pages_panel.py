from __future__ import annotations

from xw_office.bootstrap import register_default_services
from xw_office.core.config import AppConfig
from xw_office.core.container import Container
from xw_office.ui.modules.layout.sample_pages_panel import SamplePagesPanel
from xw_office.ui.modules.layout.view import LayoutView


def test_layout_view_registers_sample_pages_panel(qtbot) -> None:
    container = Container(AppConfig())
    register_default_services(container)
    view = LayoutView(container)
    qtbot.addWidget(view)

    assert view.findChild(SamplePagesPanel) is not None


def test_sample_pages_panel_add_and_remove_rows(qtbot, tmp_path) -> None:
    from xw_office.services.layout.sample_pages_service import SamplePageExportService

    panel = SamplePagesPanel(SamplePageExportService())
    qtbot.addWidget(panel)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    panel._add_pdf_paths([str(pdf_path)])  # noqa: SLF001 - UI smoke test
    assert panel._table.rowCount() == 1  # noqa: SLF001

    panel._table.selectRow(0)  # noqa: SLF001
    panel._remove_selected()  # noqa: SLF001
    assert panel._table.rowCount() == 0  # noqa: SLF001
