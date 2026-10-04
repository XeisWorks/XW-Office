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
        if logo_path.is_file():
            page.insert_image(fitz.Rect(left, area.y0 + 14, left + 78, area.y0 + 45), filename=str(logo_path), keep_proportion=True)
        page.insert_textbox(
            fitz.Rect(left, area.y0 + 48, right, area.y0 + 74),
            "PACKLISTE",
            fontsize=14,
            fontname="hebo",
            color=ink,
        )
        page.draw_rect(fitz.Rect(left, area.y0 + 74, right, area.y0 + 104), color=red, fill=red)
        page.insert_textbox(
            fitz.Rect(left + 7, area.y0 + 74, right - 7, area.y0 + 104),
            f"PAKET {context.package_number} VON {context.package_count}",
            fontsize=12,
            fontname="hebo",
            align=1,
            color=(1, 1, 1),
        )
        meta = [
            f"Bestellung: {context.reference or '-'}",
            f"Rechnung: {context.invoice_number or '-'}",
            f"Kunde: {context.customer_name or '-'}",
            f"Paketgewicht: {context.weight_kg:.2f} kg",
        ]
        page.insert_textbox(fitz.Rect(left, area.y0 + 113, right, area.y0 + 164), "\n".join(meta), fontsize=7.6, color=(0.18, 0.18, 0.18))

        y = area.y0 + 174
        page.draw_rect(fitz.Rect(left, y, right, y + 18), color=red, fill=red)
        page.insert_text((left + 6, y + 12), "Menge", fontsize=7.2, fontname="hebo", color=(1, 1, 1))
        page.insert_text((left + 47, y + 12), "Inhalt", fontsize=7.2, fontname="hebo", color=(1, 1, 1))
        y += 18
        items = context.items or (PackingListItem(0, "Keine Artikel zugeordnet"),)
        for row, item in enumerate(items[:8]):
            row_height = 22
            fill = (0.975, 0.975, 0.975) if row % 2 else (1, 1, 1)
            page.draw_rect(fitz.Rect(left, y, right, y + row_height), color=(0.86, 0.86, 0.86), fill=fill, width=0.3)
            page.insert_textbox(fitz.Rect(left + 5, y + 5, left + 39, y + 19), str(item.quantity), fontsize=8.5, fontname="hebo", align=1, color=ink)
            product = " · ".join(part for part in (item.name, item.sku) if part)[:95]
            page.insert_textbox(fitz.Rect(left + 47, y + 4, right - 5, y + 20), product, fontsize=7.1, color=ink)
            y += row_height
        if len(items) > 8:
            page.insert_textbox(fitz.Rect(left, y + 4, right, y + 18), f"+ {len(items) - 8} weitere Position(en)", fontsize=7, color=(0.35, 0.35, 0.35))

        footer_y = area.y1 - 34
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
