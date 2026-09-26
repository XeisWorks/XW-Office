"""Render selected PDF pages as web-optimized JPG sample pages.

Renders with PyMuPDF at the requested pixel height, then re-encodes as JPEG
with an auto-reduced quality (mirrors the manual scripts this replaces:
start at high quality, step down until the file fits the size budget).
"""
from __future__ import annotations

import io
import logging
import math
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from xw_office.services.layout.sample_pages_models import (
    SamplePageExportError,
    SamplePageExportResult,
    SamplePageExportSettings,
    SamplePageJob,
)

logger = logging.getLogger(__name__)

_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]+')
_START_QUALITY = 95
_MIN_QUALITY = 10
_QUALITY_STEP = 5


def _sanitize_filename_component(value: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS_RE.sub("_", value).strip().rstrip(".")
    return sanitized or "Beispielseite"


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({idx}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise SamplePageExportError(f"Kein freier Dateiname gefunden für: {path}")


class SamplePageExportService:
    """Exports chosen pages of one or more PDFs as web-optimized JPGs."""

    def export(
        self,
        jobs: Sequence[SamplePageJob],
        settings: SamplePageExportSettings,
        *,
        progress: Callable[[int, str], None] | None = None,
    ) -> list[SamplePageExportResult]:
        import fitz  # type: ignore[import-untyped]

        if not jobs:
            raise SamplePageExportError("Bitte mindestens eine PDF-Datei mit Seitenauswahl angeben.")
        if settings.target_height_px <= 0:
            raise SamplePageExportError("Die Zielhöhe muss größer als 0 sein.")
        if settings.max_size_kb <= 0:
            raise SamplePageExportError("Die maximale Dateigröße muss größer als 0 sein.")

        for job in jobs:
            overlapping_pages = sorted(set(job.pages).intersection(job.watermarked_pages))
            if overlapping_pages:
                raise SamplePageExportError(
                    f'"{job.pdf_path.name}": Seite(n) {", ".join(map(str, overlapping_pages))} '
                    "sind sowohl normal als auch mit Wasserzeichen ausgewählt."
                )

        watermark_pages_selected = any(job.watermarked_pages for job in jobs)
        watermark_rgba: Any | None = None
        if watermark_pages_selected:
            if settings.watermark_path is None:
                raise SamplePageExportError(
                    "Bitte ein Wasserzeichen-Bild für die markierten Seiten auswählen."
                )
            watermark_path = settings.watermark_path.expanduser()
            if not watermark_path.is_file():
                raise SamplePageExportError(f'Wasserzeichen-Bild nicht gefunden: "{watermark_path}".')
            from PIL import Image

            with Image.open(watermark_path) as watermark_image:
                watermark_rgba = watermark_image.convert("RGBA")

        output_folder = settings.output_folder.expanduser()
        output_folder.mkdir(parents=True, exist_ok=True)

        total_pages = sum(len(job.pages) + len(job.watermarked_pages) for job in jobs)
        if total_pages == 0:
            raise SamplePageExportError("Keine Seiten zum Exportieren ausgewählt.")

        results: list[SamplePageExportResult] = []
        done = 0
        for job in jobs:
            pdf_path = job.pdf_path.expanduser()
            if not pdf_path.is_file():
                raise SamplePageExportError(f'PDF nicht gefunden: "{pdf_path}".')
            with fitz.open(pdf_path) as doc:
                page_count = doc.page_count
                invalid = [p for p in job.pages if p < 1 or p > page_count]
                invalid.extend(p for p in job.watermarked_pages if p < 1 or p > page_count)
                if invalid:
                    raise SamplePageExportError(
                        f'"{pdf_path.name}" hat nur {page_count} Seite(n); '
                        f"ungültig: {', '.join(str(p) for p in invalid)}."
                    )
                selected_pages = sorted(
                    [(page, False) for page in job.pages]
                    + [(page, True) for page in job.watermarked_pages]
                )
                for page_number, is_watermarked in selected_pages:
                    if progress:
                        progress(round(done * 100 / total_pages), f"{pdf_path.name}: Seite {page_number} …")
                    results.append(
                        self._render_one(
                            doc,
                            pdf_path,
                            page_number,
                            output_folder,
                            settings.target_height_px,
                            settings.max_size_kb,
                            watermark_rgba=watermark_rgba,
                            is_watermarked=is_watermarked,
                        )
                    )
                    done += 1

        if progress:
            progress(100, f"{len(results)} Seite(n) exportiert.")
        return results

    def _render_one(
        self,
        doc: Any,
        pdf_path: Path,
        page_number: int,
        output_folder: Path,
        target_height_px: int,
        max_size_kb: int,
        *,
        watermark_rgba: Any | None,
        is_watermarked: bool,
    ) -> SamplePageExportResult:
        import fitz
        from PIL import Image, ImageDraw

        page = doc.load_page(page_number - 1)
        rect = page.rect
        if rect.height <= 0:
            raise SamplePageExportError(f"Seite {page_number} hat eine ungültige Höhe.")

        zoom = target_height_px / rect.height
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        if image.height != target_height_px:
            new_width = max(1, round(image.width * target_height_px / image.height))
            image = image.resize((new_width, target_height_px), Image.Resampling.LANCZOS)
        if is_watermarked:
            if watermark_rgba is None:
                raise SamplePageExportError("Wasserzeichen-Bild konnte nicht geladen werden.")
            image = self._apply_half_cut_watermark(image, watermark_rgba, Image, ImageDraw)

        stem = _sanitize_filename_component(pdf_path.stem)
        target_path = _next_available_path(output_folder / f"{stem}_S{page_number}.jpg")

        max_bytes = max_size_kb * 1024
        quality = _START_QUALITY
        buffer = io.BytesIO()
        while True:
            buffer.seek(0)
            buffer.truncate(0)
            image.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
            size = buffer.tell()
            if size <= max_bytes or quality <= _MIN_QUALITY:
                break
            quality -= _QUALITY_STEP

        target_path.write_bytes(buffer.getvalue())
        return SamplePageExportResult(
            pdf_path=pdf_path,
            page_number=page_number,
            output_path=target_path,
            quality_used=quality,
            file_size_bytes=target_path.stat().st_size,
            is_watermarked=is_watermarked,
        )

    @staticmethod
    def _apply_half_cut_watermark(
        page_image: Any,
        watermark_rgba: Any,
        image_module: Any,
        image_draw: Any,
    ) -> Any:
        """Apply the legacy diagonal half-cut watermark treatment to one rendered page."""
        canvas = page_image.convert("RGBA")
        width, height = canvas.size

        overlay = image_module.new("RGBA", canvas.size, (255, 255, 255, 0))
        draw = image_draw.Draw(overlay)
        draw.polygon(
            [(width, 0), (width, height), (0, height)],
            fill=(255, 255, 255, int(255 * 0.85)),
        )
        canvas = image_module.alpha_composite(canvas, overlay)

        watermark_width = max(1, int(width * 0.8))
        watermark_height = max(
            1,
            int(watermark_rgba.size[1] * (watermark_width / watermark_rgba.size[0])),
        )
        watermark = watermark_rgba.resize(
            (watermark_width, watermark_height), image_module.Resampling.LANCZOS
        )
        angle = math.degrees(math.atan2(height, width))
        watermark = watermark.rotate(angle, expand=True, resample=image_module.Resampling.BICUBIC)
        canvas.alpha_composite(
            watermark,
            ((width - watermark.size[0]) // 2, (height - watermark.size[1]) // 2),
        )
        return canvas.convert("RGB")
