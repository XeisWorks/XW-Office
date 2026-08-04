"""QR-code rendering: exact-pixel PNG output with an optional centered logo.

Uses ``segno`` (already a project dependency, see LayoutToolsService.generate_qr_png
and services/transfers/payment_qr.py) for the QR symbol and Pillow for compositing.
No new runtime dependency is introduced.

The QR matrix must never be scaled with interpolation - module edges have to
stay crisp for reliable scanning. The algorithm therefore renders the raw
module grid at 1 pixel/module, upscales with an integer factor using nearest-
neighbour resampling, and centers the result on an exact-size white canvas
(see markdowns/QR_Code_Untermenue_PySide6_Spezifikation.md section 19).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import segno
from PIL import Image, UnidentifiedImageError

from xw_office.services.qr_codes.models import QrRenderError, QrRenderSettings

logger = logging.getLogger(__name__)


class SegnoLogoQrRenderer:
    """Render one QR payload to PNG bytes at an exact pixel size, with an optional logo."""

    def __init__(self) -> None:
        self._logo_cache: tuple[str, Image.Image] | None = None

    def render(self, payload: str, settings: QrRenderSettings) -> bytes:
        if not payload.strip():
            raise QrRenderError("Der QR-Inhalt (Payload-URL) ist leer.")
        if settings.width_px <= 0 or settings.height_px <= 0:
            raise QrRenderError("Breite und Höhe müssen größer als 0 sein.")

        symbol_image = self._render_module_grid(payload, settings)
        module_count = symbol_image.width
        module_px = min(settings.width_px, settings.height_px) // module_count
        if module_px < 1:
            raise QrRenderError(
                f"Der QR-Code hat {module_count} Module je Seite und passt bei "
                f"{settings.width_px}x{settings.height_px} Pixel nicht mehr in ganzzahliger "
                "Modulgröße. Bitte die Ausgabegröße erhöhen."
            )
        symbol_size = module_count * module_px
        symbol_image = symbol_image.resize((symbol_size, symbol_size), Image.Resampling.NEAREST)

        canvas = Image.new("RGB", (settings.width_px, settings.height_px), settings.background_color)
        offset = (
            (settings.width_px - symbol_size) // 2,
            (settings.height_px - symbol_size) // 2,
        )
        canvas.paste(symbol_image, offset)

        if settings.logo_enabled:
            self._composite_logo(canvas, symbol_size, offset, settings, module_px)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()

    def _render_module_grid(self, payload: str, settings: QrRenderSettings) -> Image.Image:
        qr = segno.make(payload, error="h")
        buf = io.BytesIO()
        qr.save(
            buf,
            kind="png",
            scale=1,
            border=settings.border_modules,
            dark=settings.foreground_color,
            light=settings.background_color,
        )
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    def _load_logo(self, logo_path: str) -> Image.Image:
        if self._logo_cache is not None and self._logo_cache[0] == logo_path:
            return self._logo_cache[1]

        path = Path(logo_path)
        if not path.is_file():
            raise QrRenderError(f"Das Logo wurde nicht gefunden:\n{logo_path}")
        try:
            with Image.open(path) as source:
                source.load()
                logo = source.convert("RGBA")
        except (OSError, UnidentifiedImageError) as exc:
            raise QrRenderError(f"Das Logo konnte nicht gelesen werden:\n{logo_path}\n\n{exc}") from exc

        self._logo_cache = (logo_path, logo)
        return logo

    def _composite_logo(
        self,
        canvas: Image.Image,
        symbol_size: int,
        symbol_offset: tuple[int, int],
        settings: QrRenderSettings,
        module_px: int,
    ) -> None:
        logo = self._load_logo(settings.logo_path)

        # Snap the backplate to whole QR modules so it never slices a module in half -
        # a raw pixel-percentage size lands mid-module and leaves jagged black slivers
        # along the cutout edge (see markdowns/QR_Code_Untermenue_PySide6_Spezifikation.md
        # section 19 - no antialiasing/interpolation is allowed on the module grid).
        module_count = symbol_size // module_px
        raw_modules = symbol_size * settings.logo_backplate_width_percent / 100 / module_px
        backplate_modules = max(1, round(raw_modules))
        if backplate_modules % 2 == 0:
            backplate_modules += 1
        backplate_modules = min(backplate_modules, module_count)
        backplate_size = backplate_modules * module_px
        start_col = (module_count - backplate_modules) // 2
        backplate_x = symbol_offset[0] + start_col * module_px
        backplate_y = symbol_offset[1] + start_col * module_px

        content_max = max(1, round(symbol_size * settings.logo_max_width_percent / 100))

        center_x = symbol_offset[0] + symbol_size // 2
        center_y = symbol_offset[1] + symbol_size // 2

        backplate = Image.new("RGB", (backplate_size, backplate_size), settings.background_color)
        canvas.paste(backplate, (backplate_x, backplate_y))

        logo_fitted = logo.copy()
        logo_fitted.thumbnail((content_max, content_max), Image.Resampling.LANCZOS)
        paste_pos = (
            center_x - logo_fitted.width // 2,
            center_y - logo_fitted.height // 2,
        )
        canvas.paste(logo_fitted, paste_pos, mask=logo_fitted)
