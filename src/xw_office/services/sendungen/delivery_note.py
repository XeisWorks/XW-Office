"""Shared customer-facing delivery-note PDF renderer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from xw_office.services.invoice_processing.buyer_notes import BuyerNoteProduct


@dataclass(frozen=True)
class DeliveryNoteContext:
    invoice_number: str
    order_reference: str
    customer_name: str
    address_lines: tuple[str, ...]
    products: tuple[BuyerNoteProduct, ...]
    buyer_note: str
    manual_note: str = ""


class DeliveryNoteService:
    """Render the same style of customer delivery note used by Offene Sendungen."""

    def generate_pdf(self, context: DeliveryNoteContext) -> Path:
        try:
            import fitz
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PyMuPDF fuer Lieferschein-PDF nicht verfuegbar") from exc

        root = Path(__file__).resolve().parents[4]
        out_dir = root / "state" / "generated" / "lieferscheine"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self._safe_part(context.order_reference or context.invoice_number, "rechnung")
        out_path = out_dir / f"lieferschein_{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        margin = 50
        logo_path = root / "icons" / "logo NEU.png"
        if logo_path.exists():
            page.insert_image(fitz.Rect(margin, 46, margin + 150, 104), filename=str(logo_path), keep_proportion=True)
        page.insert_text((margin, 132), "LIEFERSCHEIN", fontsize=28, fontname="helv", color=(0.08, 0.08, 0.08))
        page.draw_line((margin, 146), (545, 146), color=(0.84, 0.09, 0.09), width=2.2)
        meta = [
            f"Datum: {datetime.now().strftime('%d.%m.%Y')}",
            f"Rechnung: {context.invoice_number or '-'}",
            f"Bestellung: {context.order_reference or '-'}",
            f"Kunde: {context.customer_name or '-'}",
        ]
        page.insert_textbox(fitz.Rect(330, 74, 545, 140), "\n".join(meta), fontsize=9.5, align=2, color=(0.25, 0.25, 0.25))

        y = 176
        page.insert_text((margin, y), "Lieferadresse", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
        page.insert_textbox(fitz.Rect(margin, y + 12, 280, y + 104), "\n".join(context.address_lines), fontsize=11, color=(0.05, 0.05, 0.05))
        page.insert_text((320, y), "Käufernotiz", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
        page.insert_textbox(fitz.Rect(320, y + 12, 545, y + 104), context.buyer_note[:900], fontsize=9.5, color=(0.18, 0.18, 0.18))

        y = 318
        table_x = margin
        table_w = 495
        row_h = 36
        page.draw_rect(fitz.Rect(table_x, y, table_x + table_w, y + row_h), color=(0.84, 0.09, 0.09), fill=(0.84, 0.09, 0.09))
        page.insert_text((table_x + 10, y + 18), "Menge", fontsize=10, color=(1, 1, 1))
        page.insert_text((table_x + 72, y + 18), "Produkt", fontsize=10, color=(1, 1, 1))
        page.insert_text((table_x + 360, y + 18), "Hinweis", fontsize=10, color=(1, 1, 1))
        y += row_h
        rows = context.products or (BuyerNoteProduct(quantity="", name="Produkte bitte ergaenzen"),)
        for index, product in enumerate(rows[:8]):
            fill = (0.97, 0.97, 0.97) if index % 2 else (1, 1, 1)
            page.draw_rect(fitz.Rect(table_x, y, table_x + table_w, y + row_h), color=(0.88, 0.88, 0.88), fill=fill)
            page.insert_textbox(fitz.Rect(table_x + 10, y + 7, table_x + 60, y + row_h), product.quantity, fontsize=10)
            product_text = " | ".join(part for part in (product.name, product.sku) if part)
            page.insert_textbox(fitz.Rect(table_x + 72, y + 6, table_x + 350, y + row_h), product_text, fontsize=9.5)
            page.insert_textbox(fitz.Rect(table_x + 360, y + 6, table_x + table_w - 6, y + row_h), product.note, fontsize=8.8)
            y += row_h

        if context.manual_note.strip():
            y += 24
            page.insert_text((margin, y), "Hinweis", fontsize=13, fontname="helv", color=(0.84, 0.09, 0.09))
            page.insert_textbox(fitz.Rect(margin, y + 14, 545, min(y + 110, 720)), context.manual_note.strip(), fontsize=10.5)

        footer = [
            "XeisWorks",
            "Musikverlag Mag. Bernhard Holl",
            "8912 Admont | Johnsbach 92",
            "Steiermark | Austria",
            "www.xeisworks.at",
            "office@xeisworks.at",
        ]
        footer_y = 742
        page.draw_line((margin, footer_y - 16), (545, footer_y - 16), color=(0.72, 0.72, 0.72), width=0.8)
        page.insert_textbox(fitz.Rect(margin, footer_y, 545, 820), "\n".join(footer), fontsize=9, align=1, color=(0.22, 0.22, 0.22))
        doc.save(str(out_path))
        doc.close()
        return out_path

    @staticmethod
    def _safe_part(value: object, fallback: str) -> str:
        text = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("._")
        return (text or fallback)[:80]
