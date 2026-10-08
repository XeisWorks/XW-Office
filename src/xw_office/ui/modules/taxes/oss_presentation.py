"""Read-only EU-OSS amounts; diagnostics never replace the financial summary."""
from __future__ import annotations

from decimal import Decimal
from html import escape

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QComboBox, QListView, QStyledItemDelegate, QWidget
from xw_office.services.finanzonline.amounts import tax_amount
from xw_office.services.finanzonline.oss_models import OssQuarterResult
from xw_office.ui.modules.taxes.presentation import format_euro


class QuarterComboBox(QComboBox):
    """Keep all four quarters readable despite native/material popup size hints."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ossQuarter")
        self.setMinimumWidth(230)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        popup = QListView()
        popup.setStyleSheet(
            "QListView { padding: 0px; }"
            "QListView::item { padding: 8px 12px; min-height: 28px; }"
        )
        self.setView(popup)
        self.setItemDelegate(QStyledItemDelegate(self))
        for number, months in enumerate(("Januar–März", "April–Juni", "Juli–September", "Oktober–Dezember"), 1):
            self.addItem(f"Q{number} · {months}", number)

    def showPopup(self) -> None:
        popup = self.view()
        metrics = popup.fontMetrics()
        width = max(230, max(metrics.horizontalAdvance(self.itemText(index))
                             for index in range(self.count())) + 48)
        height = max(48, metrics.height() + 32)
        popup.setMinimumWidth(width)
        popup.setMinimumHeight(height * self.count() + 4)
        if isinstance(popup, QListView):
            popup.setUniformItemSizes(True)
            popup.setGridSize(QSize(width - 4, height))
        super().showPopup()
        popup.doItemsLayout()
        popup.scrollToTop()


def oss_summary_html(result: OssQuarterResult) -> str:
    lines = [*result.goods_lines, *result.service_lines]
    net = sum((tax_amount(line.taxable_amount) for line in lines), Decimal(0))
    vat = sum((tax_amount(line.tax_amount) for line in lines), Decimal(0))

    def amounts(net_amount: Decimal, vat_amount: Decimal) -> str:
        return (
            f"<p>Mehrwertsteuer: EUR {format_euro(str(vat_amount))}<br>"
            f"Brutto: EUR {format_euro(str(net_amount + vat_amount))}<br>"
            f"Netto: EUR {format_euro(str(net_amount))}</p>"
        )

    parts = [f"<h2>EU-OSS Q{result.quarter}/{result.year}</h2>", amounts(net, vat)]
    for line in lines:
        title = f"{line.country_code} · {line.country_name} · {format_euro(line.vat_rate)} %"
        kind = "Waren" if line.goods else "Leistungen"
        parts.extend((
            f"<h3>{escape(title)} ({kind})</h3>",
            amounts(tax_amount(line.taxable_amount), tax_amount(line.tax_amount)),
        ))
    if not lines:
        parts.append("<p>Keine OSS-Umsätze. Nullmeldung direkt im Portal prüfen.</p>")
    return "".join(parts)
