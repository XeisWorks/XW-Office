"""Render PDF pages through PyMuPDF and QPrinter without external viewers."""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import fitz  # PyMuPDF
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrinter

logger = logging.getLogger(__name__)

MUSIC_DPI = 600
INVOICE_DPI = 300
PlacementMode = Literal["paper_origin", "printable_origin", "calibrated"]
PageClass = Literal["notation", "graphic", "mixed"]
RenderColorMode = Literal["auto", "rgb", "gray"]
ResolvedRenderColorMode = Literal["rgb", "gray"]
BlackEnhancement = Literal[
    "auto",
    "none",
    "darken",
    "mild_darken",
    "adaptive_music",
    "auto_music",
    "music_black",
    "threshold",
]
ResolvedBlackEnhancement = Literal[
    "none",
    "darken",
    "mild_darken",
    "adaptive_music",
    "music_black",
    "threshold",
]
_VALID_PLACEMENT_MODES = {"paper_origin", "printable_origin", "calibrated"}
_DARKEN_FACTOR = 0.78
_MILD_DARKEN_FACTOR = 0.90


@dataclass(frozen=True)
class PagePrintAnalysis:
    page_class: PageClass
    white_ratio: float
    black_ratio: float
    midtone_ratio: float
    color_ratio: float
    variation_score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class PageRenderStrategy:
    render_color_mode: ResolvedRenderColorMode
    black_enhancement: ResolvedBlackEnhancement
    analysis: PagePrintAnalysis | None = None
    notation_boost: str = "medium"


def _expand_ranges(page_ranges: list[range], page_count: int) -> list[int]:
    pages: list[int] = []
    for pr in page_ranges:
        for p in pr:
            if 0 <= p < page_count and p not in pages:
                pages.append(p)
    return pages


def page_indices_from_qprinter(printer: QPrinter, page_count: int) -> list[int] | None:
    """Map Qt print dialog page range to 0-based indices."""
    if page_count <= 0:
        return None
    pr_range = printer.printRange()
    if pr_range == QPrinter.PrintRange.AllPages:
        return None
    if pr_range == QPrinter.PrintRange.Selection:
        return None
    if pr_range != QPrinter.PrintRange.PageRange:
        return None

    start = int(printer.fromPage())
    end = int(printer.toPage())
    if start < 1 or end < 1:
        return None
    lo = max(0, start - 1)
    hi_excl = min(page_count, end)
    if lo >= hi_excl:
        return None
    return list(range(lo, hi_excl))


def mm_to_px(value_mm: float, dpi: int) -> float:
    return float(value_mm) / 25.4 * float(dpi)


def _placement_mode(value: str) -> PlacementMode:
    normalized = str(value or "paper_origin").strip().casefold()
    if normalized in _VALID_PLACEMENT_MODES:
        return cast(PlacementMode, normalized)
    return "paper_origin"


def _render_color_mode(value: str, *, job_kind: str) -> RenderColorMode:
    normalized = str(value or "auto").strip().casefold()
    if normalized in {"auto", "rgb", "gray"}:
        return cast(RenderColorMode, normalized)
    return "auto" if str(job_kind or "").strip().casefold() in {"music", "product"} else "rgb"


def _black_enhancement(value: str, *, job_kind: str) -> BlackEnhancement:
    normalized = str(value or "auto").strip().casefold()
    if normalized == "auto":
        return "auto_music" if str(job_kind or "").strip().casefold() in {"music", "product"} else "none"
    if normalized in {
        "none",
        "darken",
        "mild_darken",
        "adaptive_music",
        "auto_music",
        "music_black",
        "threshold",
    }:
        return cast(BlackEnhancement, normalized)
    return "none"


def _is_plausible_dpi(value: int) -> bool:
    return 72 <= int(value) <= 4800


def _safe_rect_tuple(rect: object) -> tuple[float, float, float, float] | None:
    try:
        return (float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))  # type: ignore[attr-defined]
    except Exception:
        return None


def _safe_printer_rect(printer: QPrinter, rect_name: str) -> tuple[float, float, float, float] | None:
    try:
        rect_func = getattr(printer, rect_name)
        return _safe_rect_tuple(rect_func(QPrinter.Unit.DevicePixel))
    except Exception:
        return None


def _safe_layout_rects(printer: QPrinter, dpi: int) -> tuple[tuple[float, float, float, float] | None, ...]:
    try:
        layout = printer.pageLayout()
    except Exception:
        return (None, None)

    full_rect = None
    paint_rect = None
    try:
        full_rect = _safe_rect_tuple(layout.fullRectPixels(dpi))
    except Exception:
        pass
    try:
        paint_rect = _safe_rect_tuple(layout.paintRectPixels(dpi))
    except Exception:
        pass
    return (full_rect, paint_rect)


def _draw_origin(*, dpi: int, x_offset_mm: float, y_offset_mm: float) -> QPointF:
    return QPointF(mm_to_px(x_offset_mm, dpi), mm_to_px(y_offset_mm, dpi))


def _enhance_gray_samples(samples: bytes, enhancement: ResolvedBlackEnhancement, threshold: int) -> bytes:
    if enhancement == "none":
        return samples
    if enhancement == "threshold":
        limit = max(0, min(int(threshold), 255))
        return bytes(0 if value <= limit else 255 for value in samples)
    if enhancement == "adaptive_music":
        table = bytes(_adaptive_music_value(value) for value in range(256))
        return samples.translate(table)
    if enhancement == "music_black":
        black_knee = max(0, min(int(threshold), 245))
        white_knee = 252
        span = max(white_knee - black_knee, 1)
        table = bytes(
            255
            if value >= white_knee
            else 0
            if value <= black_knee
            else max(0, min(int(((value - black_knee) / span) * 160), 255))
            for value in range(256)
        )
        return samples.translate(table)
    if enhancement == "mild_darken":
        table = bytes(255 if value >= 250 else max(0, min(int(value * _MILD_DARKEN_FACTOR), 255)) for value in range(256))
        return samples.translate(table)
    table = bytes(255 if value >= 250 else max(0, min(int(value * _DARKEN_FACTOR), 255)) for value in range(256))
    return samples.translate(table)


def _adaptive_music_value(value: int) -> int:
    if value >= 248:
        return 255
    if value <= 110:
        return 0
    normalized = (value - 110) / 138.0
    curved = normalized**1.75
    return max(0, min(int(curved * 190), 255))


def _render_page_image(
    page: fitz.Page,
    *,
    dpi: int,
    render_color_mode: ResolvedRenderColorMode,
    black_enhancement: ResolvedBlackEnhancement,
    black_threshold: int,
) -> QImage:
    if render_color_mode == "gray":
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
        samples = _enhance_gray_samples(bytes(pix.samples), black_enhancement, black_threshold)
        image = QImage(
            samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_Grayscale8,
        )
        return image.copy()
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    image = QImage(
        pix.samples,
        pix.width,
        pix.height,
        pix.stride,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


def classify_pdf_page_for_print(page: fitz.Page, *, sample_dpi: int = 72) -> PagePrintAnalysis:
    pix = page.get_pixmap(dpi=sample_dpi, colorspace=fitz.csRGB, alpha=False)
    samples = memoryview(pix.samples)
    total = max(int(pix.width) * int(pix.height), 1)
    white = 0
    black = 0
    midtone = 0
    color = 0
    luma_sum = 0
    luma_sq_sum = 0

    for index in range(0, len(samples), 3):
        r = int(samples[index])
        g = int(samples[index + 1])
        b = int(samples[index + 2])
        high = max(r, g, b)
        low = min(r, g, b)
        luma = (77 * r + 150 * g + 29 * b) >> 8
        if r >= 245 and g >= 245 and b >= 245:
            white += 1
        if luma <= 80:
            black += 1
        if 90 <= luma <= 235:
            midtone += 1
        if high - low > 18:
            color += 1
        luma_sum += luma
        luma_sq_sum += luma * luma

    white_ratio = white / total
    black_ratio = black / total
    midtone_ratio = midtone / total
    color_ratio = color / total
    mean = luma_sum / total
    variation = max((luma_sq_sum / total) - (mean * mean), 0.0) ** 0.5 / 255.0

    if color_ratio > 0.003:
        return PagePrintAnalysis("graphic", white_ratio, black_ratio, midtone_ratio, color_ratio, variation, "color")
    if white_ratio >= 0.84 and midtone_ratio <= 0.14 and 0.0005 <= black_ratio <= 0.24:
        return PagePrintAnalysis("notation", white_ratio, black_ratio, midtone_ratio, color_ratio, variation, "white-black")
    if midtone_ratio > 0.10 or white_ratio < 0.68:
        return PagePrintAnalysis("graphic", white_ratio, black_ratio, midtone_ratio, color_ratio, variation, "midtone")
    return PagePrintAnalysis("mixed", white_ratio, black_ratio, midtone_ratio, color_ratio, variation, "uncertain")


def _is_music_like_job(job_kind: str) -> bool:
    return str(job_kind or "").strip().casefold() in {"music", "product"}


def _resolve_page_render_strategy(
    *,
    job_kind: str,
    requested_render_color_mode: RenderColorMode,
    requested_black_enhancement: BlackEnhancement,
    analysis: PagePrintAnalysis | None,
) -> PageRenderStrategy:
    if not _is_music_like_job(job_kind):
        color = "rgb" if requested_render_color_mode == "auto" else cast(ResolvedRenderColorMode, requested_render_color_mode)
        enhancement = "none" if requested_black_enhancement in {"auto", "auto_music"} else requested_black_enhancement
        return PageRenderStrategy(color, cast(ResolvedBlackEnhancement, enhancement), analysis, "off")

    if requested_black_enhancement not in {"auto", "auto_music"}:
        color = "gray" if requested_render_color_mode == "auto" else requested_render_color_mode
        return PageRenderStrategy(
            cast(ResolvedRenderColorMode, color),
            cast(ResolvedBlackEnhancement, requested_black_enhancement),
            analysis,
            "explicit",
        )

    if requested_render_color_mode != "auto":
        color = cast(ResolvedRenderColorMode, requested_render_color_mode)
        enhancement: ResolvedBlackEnhancement = "adaptive_music" if color == "gray" else "none"
        return PageRenderStrategy(color, enhancement, analysis, "medium")

    if analysis is not None and analysis.page_class == "notation":
        return PageRenderStrategy("gray", "adaptive_music", analysis, "medium")
    if analysis is not None and analysis.page_class == "mixed":
        return PageRenderStrategy("rgb", "none", analysis, "conservative")
    return PageRenderStrategy("rgb", "none", analysis, "off")


def print_pdf_with_qprinter(
    pdf_path: str,
    printer_name: str,
    *,
    pages: list[int] | None = None,
    copies: int = 1,
    dpi: int | None = None,
    fallback_dpi: int = INVOICE_DPI,
    placement_mode: str = "paper_origin",
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
    job_kind: str = "invoice",
    render_color_mode: str = "auto",
    black_enhancement: str = "auto",
    black_threshold: int = 180,
) -> None:
    """Print a PDF with PyMuPDF + QPrinter/QPainter.

    The selected Windows printer queue is authoritative for paper size, duplex,
    tray, color, orientation, quality, and vendor-specific settings. This
    function only selects the queue, optionally sets render resolution, renders
    pages to bitmaps, and draws them without resizing.
    """
    fallback_render_dpi = max(int(fallback_dpi or INVOICE_DPI), 1)
    effective_copies = max(int(copies or 1), 1)
    effective_placement_mode = _placement_mode(placement_mode)
    effective_color_mode = _render_color_mode(render_color_mode, job_kind=job_kind)
    effective_black_enhancement = _black_enhancement(black_enhancement, job_kind=job_kind)
    full_page = effective_placement_mode in {"paper_origin", "calibrated"}
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc)
        page_indices = list(range(page_count)) if pages is None else [p for p in pages if 0 <= p < page_count]
        if not page_indices:
            logger.warning("No pages to print for %s", pdf_path)
            return
        analysis_cache: dict[int, PagePrintAnalysis] = {}

        for copy_index in range(effective_copies):
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.NativeFormat)
            printer.setPrinterName(printer_name)
            printer.setFullPage(full_page)
            requested_dpi = max(int(dpi), 1) if dpi is not None else None
            if requested_dpi is not None:
                printer.setResolution(requested_dpi)
            driver_dpi = int(printer.resolution() or 0)
            if requested_dpi is None and not _is_plausible_dpi(driver_dpi):
                printer.setResolution(fallback_render_dpi)
                driver_dpi = int(printer.resolution() or fallback_render_dpi)
            render_dpi = max(int(driver_dpi or requested_dpi or fallback_render_dpi), 1)

            painter = QPainter()
            if not painter.begin(printer):
                logger.error("QPainter.begin(printer) failed for %s", printer_name)
                return
            try:
                for page_offset, page_num in enumerate(page_indices):
                    if page_offset > 0:
                        printer.newPage()
                    page = doc[page_num]
                    analysis = None
                    if (
                        _is_music_like_job(job_kind)
                        and effective_color_mode == "auto"
                        and effective_black_enhancement in {"auto", "auto_music"}
                    ):
                        analysis = analysis_cache.get(page_num)
                        if analysis is None:
                            analysis = classify_pdf_page_for_print(page)
                            analysis_cache[page_num] = analysis
                    strategy = _resolve_page_render_strategy(
                        job_kind=job_kind,
                        requested_render_color_mode=effective_color_mode,
                        requested_black_enhancement=effective_black_enhancement,
                        analysis=analysis,
                    )
                    image = _render_page_image(
                        page,
                        dpi=render_dpi,
                        render_color_mode=strategy.render_color_mode,
                        black_enhancement=strategy.black_enhancement,
                        black_threshold=black_threshold,
                    )
                    origin = _draw_origin(dpi=render_dpi, x_offset_mm=x_offset_mm, y_offset_mm=y_offset_mm)
                    _log_page_strategy(
                        printer_name=printer_name,
                        pdf_path=pdf_path,
                        page_index=page_num,
                        job_kind=job_kind,
                        strategy=strategy,
                        dpi=render_dpi,
                    )
                    _log_page_metrics(
                        printer=printer,
                        printer_name=printer_name,
                        job_kind=job_kind,
                        placement_mode=effective_placement_mode,
                        full_page=full_page,
                        effective_dpi=render_dpi,
                        driver_dpi=driver_dpi,
                        page=page,
                        image=image,
                        x_offset_mm=x_offset_mm,
                        y_offset_mm=y_offset_mm,
                        draw_origin=origin,
                        render_color_mode=strategy.render_color_mode,
                        black_enhancement=strategy.black_enhancement,
                        black_threshold=black_threshold,
                    )
                    painter.drawImage(origin, image)
            finally:
                painter.end()
            logger.info(
                "PDF print copy dispatched: printer='%s' file='%s' copy=%s/%s dpi=%s pages=%s",
                printer_name,
                pdf_path,
                copy_index + 1,
                effective_copies,
                render_dpi,
                page_indices,
            )
    finally:
        doc.close()


# Backward-compatible name used by older UI helpers.
def print_pdf(
    pdf_path: str,
    printer: QPrinter,
    dpi: int = MUSIC_DPI,
    *,
    pages: list[int] | None = None,
    page_ranges: list[range] | None = None,
) -> None:
    page_indices = pages
    if page_indices is None and page_ranges:
        doc = fitz.open(pdf_path)
        try:
            page_indices = _expand_ranges(page_ranges, len(doc)) or None
        finally:
            doc.close()
    printer_name = str(printer.printerName() or "").strip()
    if not printer_name:
        raise RuntimeError("Kein Drucker ausgewaehlt")
    print_pdf_with_qprinter(
        pdf_path,
        printer_name,
        pages=page_indices,
        copies=1,
        dpi=dpi,
        fallback_dpi=dpi,
        placement_mode="paper_origin",
        job_kind="music",
        render_color_mode="auto",
        black_enhancement="auto_music",
    )


def _log_page_metrics(
    *,
    printer: QPrinter,
    printer_name: str,
    job_kind: str,
    placement_mode: PlacementMode,
    full_page: bool,
    effective_dpi: int,
    driver_dpi: int,
    page: fitz.Page,
    image: QImage,
    x_offset_mm: float,
    y_offset_mm: float,
    draw_origin: QPointF,
    render_color_mode: ResolvedRenderColorMode,
    black_enhancement: ResolvedBlackEnhancement,
    black_threshold: int,
) -> None:
    full_rect, paint_rect = _safe_layout_rects(printer, effective_dpi)
    logger.info(
        "PDF print page metrics: printer='%s' job_kind=%s placement_mode=%s setFullPage=%s "
        "effective_dpi=%s printer_resolution=%s pdf_page_pt=(%.3f, %.3f) image_px=(%s, %s) "
        "layout_full_rect_px=%s layout_paint_rect_px=%s qprinter_page_rect_px=%s "
        "qprinter_paper_rect_px=%s x_offset_mm=%.3f y_offset_mm=%.3f draw_px=(%.3f, %.3f) "
        "render_color_mode=%s black_enhancement=%s black_threshold=%s",
        printer_name,
        job_kind,
        placement_mode,
        full_page,
        effective_dpi,
        driver_dpi,
        float(page.rect.width),
        float(page.rect.height),
        image.width(),
        image.height(),
        full_rect,
        paint_rect,
        _safe_printer_rect(printer, "pageRect"),
        _safe_printer_rect(printer, "paperRect"),
        x_offset_mm,
        y_offset_mm,
        float(draw_origin.x()),
        float(draw_origin.y()),
        render_color_mode,
        black_enhancement,
        black_threshold,
    )


def _log_page_strategy(
    *,
    printer_name: str,
    pdf_path: str,
    page_index: int,
    job_kind: str,
    strategy: PageRenderStrategy,
    dpi: int,
) -> None:
    analysis = strategy.analysis
    logger.info(
        "PDF print page strategy: printer='%s' file='%s' page_index=%s job_kind=%s page_class=%s "
        "white_ratio=%.4f black_ratio=%.4f midtone_ratio=%.4f color_ratio=%.4f "
        "effective_render_color_mode=%s effective_black_enhancement=%s notation_boost=%s dpi=%s reason=%s",
        printer_name,
        pdf_path,
        page_index,
        job_kind,
        analysis.page_class if analysis is not None else "not_analyzed",
        analysis.white_ratio if analysis is not None else 0.0,
        analysis.black_ratio if analysis is not None else 0.0,
        analysis.midtone_ratio if analysis is not None else 0.0,
        analysis.color_ratio if analysis is not None else 0.0,
        strategy.render_color_mode,
        strategy.black_enhancement,
        strategy.notation_boost,
        dpi,
        analysis.reason if analysis is not None else "explicit",
    )


def create_calibration_pdf(
    output_path: str | Path,
    *,
    printer_name: str,
    placement_mode: str = "paper_origin",
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
) -> str:
    """Create an A4 calibration PDF with exact-size frame and measuring marks."""
    path = str(output_path)
    doc = fitz.open()
    page = doc.new_page(width=595.275590551, height=841.88976378)
    mm = 72.0 / 25.4
    width = page.rect.width
    height = page.rect.height
    page.draw_rect(page.rect, color=(0, 0, 0), width=0.3)
    page.draw_line((10 * mm, 20 * mm), (110 * mm, 20 * mm), color=(0, 0, 0), width=0.5)
    page.draw_line((10 * mm, 20 * mm), (10 * mm, 120 * mm), color=(0, 0, 0), width=0.5)
    for mark in (10, 20, 50, 100):
        x = (10 + mark) * mm
        y = (20 + mark) * mm
        page.draw_line((x, 18 * mm), (x, 22 * mm), color=(0, 0, 0), width=0.4)
        page.insert_text((x - 4 * mm, 16 * mm), f"{mark}", fontsize=7)
        page.draw_line((8 * mm, y), (12 * mm, y), color=(0, 0, 0), width=0.4)
        page.insert_text((13 * mm, y + 2 * mm), f"{mark}", fontsize=7)
    page.draw_line((0, height / 2), (width, height / 2), color=(0.6, 0.6, 0.6), width=0.2)
    page.draw_line((width / 2, 0), (width / 2, height), color=(0.6, 0.6, 0.6), width=0.2)
    page.insert_text(
        (15 * mm, 145 * mm),
        f"printer={printer_name}\nplacement={placement_mode}\nx_offset_mm={x_offset_mm}\ny_offset_mm={y_offset_mm}",
        fontsize=9,
    )
    doc.save(path)
    doc.close()
    return path


def print_calibration_page_with_qprinter(
    printer_name: str,
    *,
    placement_mode: str = "paper_origin",
    x_offset_mm: float = 0.0,
    y_offset_mm: float = 0.0,
    dpi: int | None = None,
    fallback_dpi: int = MUSIC_DPI,
) -> str:
    """Create and print a calibration PDF through the same internal renderer path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as handle:
        temp_path = handle.name
    create_calibration_pdf(
        temp_path,
        printer_name=printer_name,
        placement_mode=placement_mode,
        x_offset_mm=x_offset_mm,
        y_offset_mm=y_offset_mm,
    )
    print_pdf_with_qprinter(
        temp_path,
        printer_name,
        dpi=dpi,
        fallback_dpi=fallback_dpi,
        placement_mode=placement_mode,
        x_offset_mm=x_offset_mm,
        y_offset_mm=y_offset_mm,
        job_kind="calibration",
    )
    return temp_path
