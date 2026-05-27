"""Print job payloads for the internal printing queue."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

PrintJobKind = Literal["music", "product", "invoice", "label"]

DEFAULT_DPI_BY_KIND: dict[str, int] = {
    "music": 600,
    "product": 600,
    "invoice": 300,
    "label": 300,
}


def default_dpi_for_kind(job_kind: str) -> int:
    return DEFAULT_DPI_BY_KIND.get(str(job_kind or "").strip().casefold(), 300)


@dataclass(frozen=True)
class PdfPrintJob:
    printer_name: str
    pdf_path: str
    pages: list[int] | None = None
    copies: int = 1
    dpi: int | None = None
    job_kind: PrintJobKind = "product"
    description: str = ""
    center_on_page: bool = True
    cleanup_paths: tuple[str, ...] = field(default_factory=tuple)
    id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def effective_dpi(self) -> int:
        return max(int(self.dpi or default_dpi_for_kind(self.job_kind)), 1)

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
