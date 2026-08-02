"""Data contracts for the QR-Code series generator.

Reproduces the Excel workbook "QR-Codes Online.xlsx" register logic
(see markdowns/QR_Code_Untermenue_PySide6_Spezifikation.md) natively in
Python. Pure dataclasses, no PySide6 dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class QrModuleError(Exception):
    """Base error for the QR-code module. Always shown as plain text in dialogs."""


class QrConfigurationError(QrModuleError):
    """Invalid user input, template placeholder, or preset configuration."""


class QrPresetError(QrModuleError):
    """A requested preset/variant does not exist or is malformed."""


class QrRenderError(QrModuleError):
    """The QR symbol or logo could not be rendered."""


class QrOutputError(QrModuleError):
    """The output directory or a specific file could not be written."""


class QrVerificationError(QrModuleError):
    """A generated PNG did not decode back to its expected payload."""


CollisionPolicy = Literal["abort", "overwrite", "rename"]


@dataclass(frozen=True)
class NumericSequenceSpec:
    """A start/end/step numeric run, e.g. Excel's F5:F115 column."""

    start: int
    end: int
    step: int = 1
    minimum_width: int = 2
    number_suffix: str = ""


@dataclass(frozen=True)
class GesamtspielchenRow:
    """One row of the "Gesamtspielchen" instrument table (Excel-fixed, 12 rows)."""

    ordinal: int
    display_name: str
    slug: str


@dataclass(frozen=True)
class QrVariantPreset:
    """Immutable program default for one Excel register/variant."""

    key: str
    display_name: str
    generation_mode: Literal["numeric", "table"]
    id_template: str
    sequence: NumericSequenceSpec | None = None
    table_rows: tuple[GesamtspielchenRow, ...] = ()
    base_domain: str = "https://www.xeisworks.at"
    base_path_template: str = ""
    id_suffix: str = ""
    default_series_code: str = ""
    default_project_slug: str = ""
    default_instrument_slug: str = ""
    uses_canonical_router: bool = False
    legacy_note: str = ""


@dataclass(frozen=True)
class QrRecord:
    """One resolved output record: logical id, target URL, and safe filename."""

    ordinal: int
    source_key: str
    logical_id: str
    payload_url: str
    output_filename: str
    warning: str = ""


@dataclass(frozen=True)
class QrRenderSettings:
    """Global QR graphics settings, persisted as one JSON blob."""

    width_px: int = 1000
    height_px: int = 1000
    output_format: str = "png"
    error_correction: str = "H"
    border_modules: int = 4
    foreground_color: str = "#000000"
    background_color: str = "#FFFFFF"
    logo_enabled: bool = True
    logo_path: str = (
        r"C:\Users\XeisWorks\OneDrive - XeisWorks\02 XeisWorks\16 QR Codes\musikheroes_qr.png"
    )
    logo_max_width_percent: float = 18.0
    logo_backplate_width_percent: float = 22.0
    last_output_directory: str = ""
    collision_policy: CollisionPolicy = "abort"
    verify_after_generation: bool = False


@dataclass(frozen=True)
class QrBatchRequest:
    """One generation run: resolved records plus render/output configuration."""

    variant_key: str
    records: tuple[QrRecord, ...]
    output_directory: Path
    render_settings: QrRenderSettings
    collision_policy: CollisionPolicy = "abort"


@dataclass(frozen=True)
class QrGenerationResult:
    """Outcome for a single record within a batch."""

    record: QrRecord
    output_path: Path | None
    success: bool
    error_message: str = ""


@dataclass(frozen=True)
class QrBatchSummary:
    """Aggregate outcome of a full batch run, shown in the completion dialog."""

    results: tuple[QrGenerationResult, ...]
    output_directory: Path
    manifest_path: Path | None
    cancelled: bool = False

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)
