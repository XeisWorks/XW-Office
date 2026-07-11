"""PDF layout tooling facade — QR-Code, blank pages, covers, ISBN."""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)
_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]+')
_DEFAULT_WATERMARK_TEXT = "Licensed Copy for {user_name} - Redistribution Prohibited"


def _clean_pdf_path(value: str | Path) -> Path:
    raw = str(value).strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return Path(raw).expanduser()


def _mm_to_points(mm: float) -> float:
    return mm * 72.0 / 25.4


def _build_a5_target_rects(
    fitz_module: object,
    a4_width: float,
    a4_height: float,
    margin_pt: float,
) -> tuple[object, object]:
    """Return two landscape A5 slots centered in the upper and lower A4 halves."""
    a5_width, a5_height = fitz_module.paper_size("a5")
    slot_width = max(a5_width, a5_height)
    slot_height = min(a5_width, a5_height)
    half_height = a4_height / 2.0
    x0 = (a4_width - slot_width) / 2.0

    top_y0 = (half_height - slot_height) / 2.0
    bottom_y0 = half_height + (half_height - slot_height) / 2.0

    top_rect = fitz_module.Rect(x0, top_y0, x0 + slot_width, top_y0 + slot_height)
    bottom_rect = fitz_module.Rect(x0, bottom_y0, x0 + slot_width, bottom_y0 + slot_height)

    if margin_pt:
        top_rect = fitz_module.Rect(
            top_rect.x0 + margin_pt,
            top_rect.y0 + margin_pt,
            top_rect.x1 - margin_pt,
            top_rect.y1 - margin_pt,
        )
        bottom_rect = fitz_module.Rect(
            bottom_rect.x0 + margin_pt,
            bottom_rect.y0 + margin_pt,
            bottom_rect.x1 - margin_pt,
            bottom_rect.y1 - margin_pt,
        )

    if top_rect.width <= 0 or top_rect.height <= 0 or bottom_rect.width <= 0 or bottom_rect.height <= 0:
        raise ValueError("Der Rand ist groesser als das verfuegbare A5-Zielfeld.")
    return top_rect, bottom_rect


def _fit_rect(fitz_module: object, target: object, width: float, height: float) -> object:
    if width <= 0 or height <= 0:
        return fitz_module.Rect(target)
    scale = min(target.width / width, target.height / height)
    fitted_width = width * scale
    fitted_height = height * scale
    x0 = target.x0 + (target.width - fitted_width) / 2.0
    y0 = target.y0 + (target.height - fitted_height) / 2.0
    return fitz_module.Rect(x0, y0, x0 + fitted_width, y0 + fitted_height)


def _normalize_page_rotations(doc: object) -> None:
    for page in doc:
        if page.rotation:
            page.remove_rotation()


def _sanitize_filename_component(value: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS_RE.sub("_", value).strip().rstrip(".")
    return sanitized or "Licensed Copy"


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({idx}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Kein freier Dateiname gefunden fuer: {path}")


def _watermark_output_path(source_pdf: Path, target_dir: Path, user_name: str) -> Path:
    safe_name = _sanitize_filename_component(user_name)
    replacement = f" - {safe_name}"
    source_name = source_pdf.name
    output_name = source_name.replace(" GESAMT", replacement)
    if output_name == source_name:
        output_name = source_name.replace("GESAMT", replacement)
    if output_name == source_name:
        output_name = f"{source_pdf.stem}{replacement}{source_pdf.suffix}"
    return _next_available_path(target_dir / output_name)


def _insert_side_watermark(
    fitz_module: object,
    document: object,
    user_name: str,
    *,
    font_size: float = 12.0,
    side_margin_mm: float = 6.0,
    opacity: float = 0.5,
    text_template: str = _DEFAULT_WATERMARK_TEXT,
) -> None:
    watermark_text = text_template.format(user_name=user_name.strip())
    x_offset = _mm_to_points(side_margin_mm)
    text_width = fitz_module.get_text_length(watermark_text, fontname="helv", fontsize=font_size)

    for page in document:
        page_width = page.rect.width
        page_height = page.rect.height
        y_center = page_height / 2.0
        insert_kwargs = {
            "fontsize": font_size,
            "color": (0, 0, 0),
            "fill_opacity": opacity,
        }
        page.insert_text(
            (x_offset, y_center + (text_width / 2.0)),
            watermark_text,
            rotate=90,
            **insert_kwargs,
        )
        page.insert_text(
            (page_width - x_offset, y_center - (text_width / 2.0)),
            watermark_text,
            rotate=270,
            **insert_kwargs,
        )


class LayoutToolsService:
    """Coordinate layout operations using PyMuPDF and segno."""

    # ------------------------------------------------------------------
    # Tool description (for overview cards)
    # ------------------------------------------------------------------

    def describe_tools(self) -> list[tuple[str, str]]:
        return [
            ("A5 -> A4", "A5-Noten doppelt auf A4 platzieren"),
            ("Leerseiten", "PDFs um neutrale Seiten erweitern"),
            ("QR-Code", "URLs/Text als QR erzeugen (segno)"),
            ("Deckblatt", "Titel-Layouts aus Vorlagen"),
            ("ISBN / Barcode", "stdnum + Renderer"),
        ]

    # ------------------------------------------------------------------
    # A5 duplication for sheet music
    # ------------------------------------------------------------------

    def default_a5_duplicate_output_path(self, source_pdf: str | Path) -> Path:
        """Return the conventional sibling output path without touching the file system."""
        source_path = _clean_pdf_path(source_pdf)
        return source_path.with_name(f"{source_path.stem}_A4-2x{source_path.suffix or '.pdf'}")

    def duplicate_a5_to_a4(
        self,
        source_pdf: str | Path,
        *,
        output_pdf: str | Path | None = None,
        margin_mm: float = 0.0,
        overwrite: bool = False,
    ) -> Path:
        """Duplicate every source page into the upper and lower A4 half.

        The operation is intentionally path-based to avoid keeping large print PDFs in memory.
        Mixed page rotations are normalized on a per-page working copy before placement.
        """
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        source_path = _clean_pdf_path(source_pdf).resolve(strict=False)
        if not source_path.is_file():
            raise FileNotFoundError(f"PDF nicht gefunden: {source_path}")
        if source_path.suffix.lower() != ".pdf":
            raise ValueError("Bitte eine PDF-Datei auswaehlen.")
        if margin_mm < 0:
            raise ValueError("Der Rand darf nicht negativ sein.")

        target_path = (
            _clean_pdf_path(output_pdf).resolve(strict=False)
            if output_pdf is not None
            else self.default_a5_duplicate_output_path(source_path).resolve(strict=False)
        )
        if target_path.suffix.lower() != ".pdf":
            target_path = target_path.with_suffix(".pdf")
        if target_path == source_path:
            raise ValueError("Ausgabe darf die Quelldatei nicht ueberschreiben.")
        if target_path.exists() and not overwrite:
            raise FileExistsError(f"Ausgabe existiert bereits: {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)

        margin_pt = _mm_to_points(margin_mm)

        with fitz.open(source_path) as source_doc:
            if source_doc.needs_pass:
                raise ValueError("Passwortgeschuetzte PDFs werden nicht unterstuetzt.")
            if len(source_doc) == 0:
                raise ValueError("Die PDF-Datei enthaelt keine Seiten.")

            output_doc = fitz.open()
            try:
                a4_width, a4_height = fitz.paper_size("a4")
                top_target, bottom_target = _build_a5_target_rects(fitz, a4_width, a4_height, margin_pt)

                for page_num in range(len(source_doc)):
                    output_page = output_doc.new_page(width=a4_width, height=a4_height)
                    source_page = source_doc.load_page(page_num)
                    if source_page.rect.is_empty:
                        continue

                    page_doc = fitz.open()
                    try:
                        page_doc.insert_pdf(source_doc, from_page=page_num, to_page=page_num)
                        _normalize_page_rotations(page_doc)
                        normalized_page = page_doc[0]

                        top_rect = _fit_rect(
                            fitz,
                            top_target,
                            normalized_page.rect.width,
                            normalized_page.rect.height,
                        )
                        bottom_rect = _fit_rect(
                            fitz,
                            bottom_target,
                            normalized_page.rect.width,
                            normalized_page.rect.height,
                        )

                        output_page.show_pdf_page(top_rect, page_doc, 0, keep_proportion=True)
                        output_page.show_pdf_page(bottom_rect, page_doc, 0, keep_proportion=True)
                    finally:
                        page_doc.close()

                save_kwargs = {
                    "garbage": 4,
                    "deflate": True,
                    "deflate_images": True,
                    "deflate_fonts": True,
                    "use_objstms": 1,
                }
                try:
                    output_doc.save(target_path, **save_kwargs)
                except TypeError:
                    save_kwargs.pop("use_objstms", None)
                    output_doc.save(target_path, **save_kwargs)
            finally:
                output_doc.close()

        return target_path

    def watermark_side_a4_pdf(
        self,
        source_pdf: str | Path,
        *,
        output_dir: str | Path,
        user_name: str,
        font_size: float = 12.0,
        side_margin_mm: float = 6.0,
        opacity: float = 0.5,
    ) -> Path:
        """Create a side-watermarked licensed PDF without overwriting existing files."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        cleaned_name = str(user_name or "").strip()
        if not cleaned_name:
            raise ValueError("Bitte einen Namen fuer das Wasserzeichen eingeben.")

        source_path = _clean_pdf_path(source_pdf).resolve(strict=False)
        if not source_path.is_file():
            raise FileNotFoundError(f"PDF nicht gefunden: {source_path}")
        if source_path.suffix.lower() != ".pdf":
            raise ValueError("Bitte eine PDF-Datei auswaehlen.")

        target_dir = _clean_pdf_path(output_dir).resolve(strict=False)
        target_dir.mkdir(parents=True, exist_ok=True)
        output_path = _watermark_output_path(source_path, target_dir, cleaned_name)
        if output_path.resolve(strict=False) == source_path.resolve(strict=False):
            raise ValueError("Ausgabe darf die Quelldatei nicht ueberschreiben.")

        with fitz.open(source_path) as document:
            if document.needs_pass:
                raise ValueError("Passwortgeschuetzte PDFs werden nicht unterstuetzt.")
            if len(document) == 0:
                raise ValueError("Die PDF-Datei enthaelt keine Seiten.")
            _insert_side_watermark(
                fitz,
                document,
                cleaned_name,
                font_size=font_size,
                side_margin_mm=side_margin_mm,
                opacity=opacity,
            )
            document.save(output_path)

        return output_path

    # ------------------------------------------------------------------
    # QR-Code generation
    # ------------------------------------------------------------------

    def generate_qr_png(
        self,
        text: str,
        *,
        scale: int = 10,
        dark: str = "#000000",
        light: str = "#ffffff",
    ) -> bytes:
        """Return a QR-Code as PNG bytes."""
        try:
            import segno  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("segno not installed") from exc

        qr = segno.make(text, error="m")
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=scale, dark=dark, light=light)
        return buf.getvalue()

    def validate_isbn(self, isbn_str: str) -> tuple[bool, str]:
        """Validate ISBN-10 or ISBN-13. Returns (is_valid, canonical_or_error)."""
        try:
            from stdnum import isbn as _isbn  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("python-stdnum not installed") from exc

        s = isbn_str.strip()
        if _isbn.is_valid(s):
            return True, _isbn.format(s)
        return False, f"Ungueltige ISBN: {_isbn.compact(s)}"

    # ------------------------------------------------------------------
    # Blank-page insertion
    # ------------------------------------------------------------------

    def insert_blank_pages(
        self,
        source_pdf: bytes | Path,
        *,
        insert_after: list[int],
        width_pt: float = 595.28,
        height_pt: float = 841.89,
    ) -> bytes:
        """Insert blank A4 pages after the given 0-based page indices."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        raw = Path(source_pdf).read_bytes() if isinstance(source_pdf, Path) else source_pdf
        doc = fitz.open(stream=raw, filetype="pdf")
        for pos in sorted(set(insert_after), reverse=True):
            insert_at = max(0, min(pos + 1, len(doc)))
            doc.insert_page(insert_at, width=width_pt, height=height_pt)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def generate_cover_pdf(
        self,
        title: str,
        subtitle: str = "",
        *,
        author: str = "",
        isbn: str = "",
        width_pt: float = 595.28,
        height_pt: float = 841.89,
        font_size_title: float = 32.0,
        font_size_subtitle: float = 18.0,
    ) -> bytes:
        """Generate a minimal text-based cover page PDF."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("PyMuPDF not installed") from exc

        doc = fitz.open()
        page = doc.new_page(width=width_pt, height=height_pt)
        x_title = width_pt * 0.1
        y_title = height_pt * 0.4
        page.insert_text((x_title, y_title), title, fontsize=font_size_title, color=(0, 0, 0))
        if subtitle:
            page.insert_text(
                (x_title, y_title + font_size_title * 1.6),
                subtitle,
                fontsize=font_size_subtitle,
                color=(0.3, 0.3, 0.3),
            )
        details = [value for value in (author.strip(), isbn.strip()) if value]
        if details:
            page.insert_text(
                (x_title, y_title + font_size_title * 2.6),
                " | ".join(details),
                fontsize=12.0,
                color=(0.35, 0.35, 0.35),
            )
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
