"""Print job payloads for the internal printing queue."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

PrintJobKind = Literal["music", "product", "invoice", "label"]
PlacementMode = Literal["paper_origin", "printable_origin", "calibrated"]
RenderColorMode = Literal["auto", "rgb", "gray"]
BlackEnhancement = Literal["auto", "none", "darken", "music_black", "threshold"]

DEFAULT_DPI_BY_KIND: dict[str, int] = {
    "music": 600,
    "product": 600,
    "invoice": 300,
    "label": 300,
}
DEFAULT_RENDER_COLOR_MODE_BY_KIND: dict[str, RenderColorMode] = {
    "music": "gray",
    "product": "gray",
    "invoice": "rgb",
    "label": "rgb",
}
DEFAULT_BLACK_ENHANCEMENT_BY_KIND: dict[str, BlackEnhancement] = {
    "music": "music_black",
    "product": "music_black",
    "invoice": "none",
    "label": "none",
}


def default_dpi_for_kind(job_kind: str) -> int:
    return DEFAULT_DPI_BY_KIND.get(str(job_kind or "").strip().casefold(), 300)


def default_render_color_mode_for_kind(job_kind: str) -> RenderColorMode:
    return DEFAULT_RENDER_COLOR_MODE_BY_KIND.get(str(job_kind or "").strip().casefold(), "rgb")


def default_black_enhancement_for_kind(job_kind: str) -> BlackEnhancement:
    return DEFAULT_BLACK_ENHANCEMENT_BY_KIND.get(str(job_kind or "").strip().casefold(), "none")


@dataclass(frozen=True)
class PdfPrintJob:
    printer_name: str
    pdf_path: str
    pages: list[int] | None = None
    copies: int = 1
    dpi: int | None = None
    job_kind: PrintJobKind = "product"
    description: str = ""
    placement_mode: PlacementMode = "paper_origin"
    x_offset_mm: float = 0.0
    y_offset_mm: float = 0.0
    render_color_mode: RenderColorMode = "auto"
    black_enhancement: BlackEnhancement = "auto"
    black_threshold: int = 180
    cleanup_paths: tuple[str, ...] = field(default_factory=tuple)
    id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def effective_dpi(self) -> int:
        return max(int(self.dpi or default_dpi_for_kind(self.job_kind)), 1)

    @property
    def effective_render_color_mode(self) -> RenderColorMode:
        if self.render_color_mode != "auto":
            return self.render_color_mode
        return default_render_color_mode_for_kind(self.job_kind)

    @property
    def effective_black_enhancement(self) -> BlackEnhancement:
        if self.black_enhancement != "auto":
            return self.black_enhancement
        return default_black_enhancement_for_kind(self.job_kind)

    @property
    def source_name(self) -> str:
        return self.description or Path(self.pdf_path).name


@dataclass(frozen=True)
class BrotherLbxLabelJob:
    printer_name: str
    template_path: str
    lines: list[str]
    overlay_object: str | None = None
    overlay_text: str | None = None
    description: str = "Brother LBX label"
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class PrintJobResult:
    job_id: str
    success: bool
    description: str
    printer_name: str
    message: str = ""
