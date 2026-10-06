"""Compact PLC packing lists: two portrait A6 slips on one landscape A5 label."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re


@dataclass(frozen=True)
class PackingListItem:
    """One physical product assigned to exactly one parcel."""

    quantity: int
    name: str
    sku: str = ""
    display_quantity: str = ""


@dataclass(frozen=True)
class PackingListContext:
    """Customer-neutral package-content slip printed inside a parcel."""

    reference: str
    invoice_number: str
    customer_name: str
    package_number: int
    package_count: int
    weight_kg: float
    items: tuple[PackingListItem, ...]


class PackingListService:
    """Render paired A6 portrait packing lists onto landscape A5 PDF pages."""

    def generate_pdf(self, contexts: tuple[PackingListContext, ...], *, output_dir: Path) -> Path:
        if not contexts:
            raise ValueError("Mindestens eine Packliste wird benötigt")
        try:
            import fitz
        except Exception as exc:  # pragma: no cover - dependency is mandatory in production.
            raise RuntimeError("PyMuPDF für Packlisten-PDF nicht verfügbar") from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        reference = self._safe_part(contexts[0].reference, "bestellung")
        target = output_dir / f"packlisten_{reference}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        root = Path(__file__).resolve().parents[4]
        logo_path = root / "icons" / "logo NEU.png"

        a5_portrait_width, a5_portrait_height = fitz.paper_size("a5")
        a6_width = a5_portrait_height / 2
        a6_height = a5_portrait_width
        document = fitz.open()
        for index in range(0, len(contexts), 2):
            # Use exact A5 geometry. The two half-pages are each A6 portrait.
            page = document.new_page(width=a5_portrait_height, height=a5_portrait_width)
            self._draw_slip(page, fitz.Rect(0, 0, a6_width, a6_height), contexts[index], logo_path)
            if index + 1 < len(contexts):
                self._draw_slip(
                    page,
                    fitz.Rect(a6_width, 0, a6_width * 2, a6_height),
                    contexts[index + 1],
                    logo_path,
                )
            page.draw_line(
                (a6_width, 7),
                (a6_width, a6_height - 7),
                color=(0.72, 0.72, 0.72),
                width=0.7,
                dashes="[2 2] 0",
            )
        document.set_metadata({"title": "XeisWorks Packlisten", "producer": "XW-Office PLC PackingList"})
        document.save(str(target))
        document.close()
        return target

    @staticmethod
    def _draw_slip(page: object, rect: object, context: PackingListContext, logo_path: Path) -> None:
        import fitz

        area = fitz.Rect(rect)
        margin = 15
        left = area.x0 + margin
        right = area.x1 - margin
        red = (0.84, 0.09, 0.09)
        ink = (0.08, 0.08, 0.08)

        page.draw_rect(area, color=(0.82, 0.82, 0.82), width=0.6)
        header_left = area.x0 + 9
        header_right = area.x1 - 8
        logo_width = 105
        header_top = area.y0 + 9
        if logo_path.is_file():
            page.insert_image(
                fitz.Rect(header_right - logo_width, header_top, header_right, header_top + 48),
                filename=str(logo_path),
                keep_proportion=True,
            )
        page.insert_textbox(
            fitz.Rect(header_left, header_top + 11, header_right - logo_width - 7, header_top + 38),
            "PACKLISTE",
            fontsize=14,
            fontname="hebo",
            color=ink,
        )
        parcel_header_top = area.y0 + 64
        parcel_header_height = 20
        parcel_title = f"PAKET {context.package_number} VON {context.package_count}"
        page.draw_rect(
            fitz.Rect(left, parcel_header_top, right, parcel_header_top + parcel_header_height),
            color=red,
            fill=red,
        )
        parcel_title_width = fitz.get_text_length(parcel_title, fontname="hebo", fontsize=12)
        page.insert_text(
            (left + (right - left - parcel_title_width) / 2, parcel_header_top + 14),
            parcel_title,
            fontsize=12,
            fontname="hebo",
            color=(1, 1, 1),
        )
        meta = [
            f"Bestellung: {context.reference or '-'}",
            f"Rechnung: {context.invoice_number or '-'}",
            f"Kunde: {context.customer_name or '-'}",
            f"Paketgewicht: {context.weight_kg:.2f} kg",
        ]
        page.insert_textbox(fitz.Rect(left, area.y0 + 93, right, area.y0 + 144), "\n".join(meta), fontsize=7.6, color=(0.18, 0.18, 0.18))

        y = area.y0 + 154
        page.draw_rect(fitz.Rect(left, y, right, y + 18), color=red, fill=red)
        page.insert_text((left + 6, y + 12), "Menge", fontsize=7.2, fontname="hebo", color=(1, 1, 1))
        page.insert_text((left + 47, y + 12), "Inhalt", fontsize=7.2, fontname="hebo", color=(1, 1, 1))
        y += 18
        items = context.items or (PackingListItem(0, "Keine Artikel zugeordnet"),)
        footer_y = area.y1 - 34
        max_printed_items = 16
        displayed_items = items[:max_printed_items]
        overflow_count = len(items) - len(displayed_items)
        rows_bottom = footer_y - (18 if overflow_count else 8)
        available_height = max(0, rows_bottom - y)
        row_height = min(22, available_height / max(1, len(displayed_items)))
        quantity_font_size = min(8.5, max(5.3, row_height * 0.39))
        product_font_size = min(7.1, max(5.0, row_height * 0.32))
        for row, item in enumerate(displayed_items):
            fill = (0.975, 0.975, 0.975) if row % 2 else (1, 1, 1)
            page.draw_rect(fitz.Rect(left, y, right, y + row_height), color=(0.86, 0.86, 0.86), fill=fill, width=0.3)
            quantity = item.display_quantity or str(item.quantity)
            quantity_width = fitz.get_text_length(quantity, fontname="hebo", fontsize=quantity_font_size)
            page.insert_text(
                (left + 22 - quantity_width / 2, y + row_height * 0.68),
                quantity,
                fontsize=quantity_font_size,
                fontname="hebo",
                color=ink,
            )
            product = " · ".join(part for part in (item.name, item.sku) if part)[:95]
            page.insert_textbox(
                fitz.Rect(left + 47, y + 1, right - 5, y + row_height - 1),
                product,
                fontsize=product_font_size,
                color=ink,
            )
            y += row_height
        if overflow_count:
            page.insert_textbox(
                fitz.Rect(left, y + 4, right, y + 16),
                f"+ {overflow_count} weitere Position(en)",
                fontsize=6.2,
                color=(0.35, 0.35, 0.35),
            )

        page.draw_line((left, footer_y), (right, footer_y), color=(0.72, 0.72, 0.72), width=0.5)
        page.insert_textbox(
            fitz.Rect(left, footer_y + 5, right, area.y1 - 7),
            f"XeisWorks · erstellt {datetime.now().strftime('%d.%m.%Y')}",
            fontsize=6.7,
            align=1,
            color=(0.3, 0.3, 0.3),
        )

    @staticmethod
    def _safe_part(value: object, fallback: str) -> str:
        cleaned = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("._")
        return (cleaned or fallback)[:80]
