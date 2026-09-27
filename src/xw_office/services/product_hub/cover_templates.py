"""Private OneDrive-backed cover-template discovery and preparation.

Cover backgrounds and commercial font files stay outside the repository. This
module only reads explicitly configured folders, derives private thumbnails, and
prepares proportionally scaled text-free backgrounds. The card, shadow, and
black bar already belong to the approved background and are never redrawn.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from xw_office.services.product_hub.onedrive import OneDriveAssetClient, OneDriveItem

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
_FONT_EXTENSIONS = {".ttf", ".otf"}
_THUMBNAIL_SIZE = (240, 320)
_DEFAULT_SPEC_PATH = (
    Path(__file__).resolve().parents[4] / "markdowns" / "unifying product flow" / "COVER_SPEC.yaml"
)


class CoverConfigurationError(RuntimeError):
    """The private cover setup or rendering contract is invalid."""


@dataclass(frozen=True)
class CoverRenderSpec:
    source_width_px: int
    source_height_px: int
    output_height_px: int
    output_format: str
    preserve_aspect_ratio: bool
    required_families: tuple[str, ...]

    @property
    def output_width_px(self) -> int:
        return round(self.source_width_px * self.output_height_px / self.source_height_px)


@dataclass(frozen=True)
class CoverTemplate:
    item_id: str
    name: str
    etag: str
    size: int


@dataclass(frozen=True)
class CoverFontReadiness:
    available_families: tuple[str, ...]
    missing_families: tuple[str, ...]

    @property
    def export_ready(self) -> bool:
        return not self.missing_families


@dataclass(frozen=True)
class PreparedCoverBackground:
    """A proportional, text-free background for the later T11 renderer."""

    content: bytes
    mime_type: str
    width: int
    height: int
    template: CoverTemplate


class CoverTemplateService:
    def __init__(
        self,
        client: OneDriveAssetClient,
        *,
        template_folder_id: str,
        font_folder_id: str,
        spec_path: Path | None = None,
    ) -> None:
        self._client = client
        self._template_folder_id = template_folder_id.strip()
        self._font_folder_id = font_folder_id.strip()
        if not self._template_folder_id or not self._font_folder_id:
            raise CoverConfigurationError("Cover templates and private font folders must be configured")
        client.assert_within_root(client.root_drive_id, self._template_folder_id)
        client.assert_within_root(client.root_drive_id, self._font_folder_id)
        self._spec = _load_spec(spec_path or _DEFAULT_SPEC_PATH)

    @classmethod
    def from_environment(cls) -> "CoverTemplateService":
        configured_spec = os.getenv("XW_COVER_SPEC_PATH", "").strip()
        return cls(
            OneDriveAssetClient.from_environment(),
            template_folder_id=os.getenv("XW_COVER_TEMPLATE_FOLDER_ID", ""),
            font_folder_id=os.getenv("XW_COVER_FONT_FOLDER_ID", ""),
            spec_path=Path(configured_spec) if configured_spec else None,
        )

    @property
    def render_spec(self) -> CoverRenderSpec:
        return self._spec

    def list_templates(self) -> list[CoverTemplate]:
        items = self._client.list_children(self._template_folder_id)
        templates = [
            CoverTemplate(item_id=item.item_id, name=item.name, etag=item.etag, size=item.size)
            for item in items
            if not item.is_folder and Path(item.name).suffix.casefold() in _IMAGE_EXTENSIONS
        ]
        return sorted(templates, key=lambda item: (item.name.casefold(), item.item_id))

    def thumbnail(self, template_id: str) -> bytes:
        """Return a small private JPEG preview, never a Graph URL or full source."""
        from PIL import Image

        image, _template = self._open_template(template_id)
        thumbnail = image.copy()
        thumbnail.thumbnail(_THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        thumbnail.save(output, format="JPEG", quality=85, optimize=True)
        return output.getvalue()

    def prepare_background(self, template_id: str) -> PreparedCoverBackground:
        """Scale a compatible background proportionally, without adding graphics."""
        from PIL import Image

        image, template = self._open_template(template_id)
        expected_ratio = self._spec.source_width_px / self._spec.source_height_px
        actual_ratio = image.width / image.height if image.height else 0
        if not actual_ratio or abs(actual_ratio / expected_ratio - 1) > 0.01:
            raise CoverConfigurationError(f"Cover template '{template.name}' has an incompatible aspect ratio")
        scaled = image.resize(
            (self._spec.output_width_px, self._spec.output_height_px), Image.Resampling.LANCZOS
        )
        output = io.BytesIO()
        pillow_format = "JPEG" if self._spec.output_format == "jpg" else "PNG"
        scaled.save(output, format=pillow_format, quality=95, optimize=True)
        return PreparedCoverBackground(
            content=output.getvalue(),
            mime_type="image/jpeg" if self._spec.output_format == "jpg" else "image/png",
            width=scaled.width,
            height=scaled.height,
            template=template,
        )

    def font_readiness(self) -> CoverFontReadiness:
        items = self._client.list_children(self._font_folder_id)
        available: set[str] = set()
        for item in items:
            if item.is_folder or Path(item.name).suffix.casefold() not in _FONT_EXTENSIONS:
                continue
            available.update(self._font_families(item))
        missing = tuple(
            family for family in self._spec.required_families if family.casefold() not in available
        )
        return CoverFontReadiness(tuple(sorted(available)), missing)

    def _open_template(self, template_id: str):
        from PIL import Image, ImageOps, UnidentifiedImageError

        template = next((item for item in self.list_templates() if item.item_id == template_id), None)
        if template is None:
            raise KeyError("Cover template was not found in the configured template folder")
        try:
            content = self._client.download(self._client.root_drive_id, template.item_id)
            with Image.open(io.BytesIO(content)) as source:
                return ImageOps.exif_transpose(source).convert("RGB"), template
        except (OSError, UnidentifiedImageError) as exc:
            raise CoverConfigurationError(f"Cover template '{template.name}' cannot be loaded") from exc

    def _font_families(self, item: OneDriveItem) -> set[str]:
        content = self._client.download(item.drive_id, item.item_id)
        with TemporaryDirectory(prefix="xw-cover-font-") as directory:
            path = Path(directory) / item.name
            path.write_bytes(content)
            try:
                from PIL import ImageFont

                family, _style = ImageFont.truetype(str(path), size=16).getname()
            except Exception as exc:  # noqa: BLE001 - bad private font gets an explicit error below
                raise CoverConfigurationError(f"Private font '{item.name}' cannot be loaded") from exc
        return {str(family).strip().casefold()} if str(family).strip() else set()


def _load_spec(path: Path) -> CoverRenderSpec:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CoverConfigurationError(f"COVER_SPEC cannot be loaded: {path}") from exc
    if not isinstance(raw, dict):
        raise CoverConfigurationError("COVER_SPEC must contain an object")
    template = raw.get("template")
    styles = raw.get("text_styles")
    if not isinstance(template, dict) or not isinstance(styles, dict):
        raise CoverConfigurationError("COVER_SPEC is missing template or text_styles")
    source_size = template.get("source_size_px")
    output_height = template.get("output_height_px")
    output_format = str(template.get("format") or "").casefold()
    if (
        not isinstance(source_size, list)
        or len(source_size) != 2
        or not all(isinstance(value, int) and value > 0 for value in source_size)
        or not isinstance(output_height, int)
        or output_height <= 0
        or output_format not in {"jpg", "png"}
    ):
        raise CoverConfigurationError("COVER_SPEC contains invalid image dimensions or format")
    if template.get("draw_card") is not False or template.get("draw_shadow") is not False or template.get("draw_black_bar") is not False:
        raise CoverConfigurationError("COVER_SPEC must keep card, shadow, and black bar inside the background")
    if template.get("preserve_aspect_ratio") is not True:
        raise CoverConfigurationError("COVER_SPEC must require proportional background scaling")
    required_families: list[str] = []
    for style in styles.values():
        family = style.get("family") if isinstance(style, dict) else None
        if isinstance(family, str) and family.strip() and family not in required_families:
            required_families.append(family)
    if not required_families:
        raise CoverConfigurationError("COVER_SPEC does not declare any font families")
    return CoverRenderSpec(
        source_width_px=source_size[0],
        source_height_px=source_size[1],
        output_height_px=output_height,
        output_format=output_format,
        preserve_aspect_ratio=True,
        required_families=tuple(required_families),
    )
