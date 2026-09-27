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
    boxes: dict[str, tuple[float, float, float, float]]
    styles: dict[str, dict[str, object]]

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


@dataclass(frozen=True)
class CoverPreviewRequest:
    template_id: str
    composer: str = ""
    title: str = ""
    arranger: str = ""
    edition: str = ""


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

    def render_preview(self, request: CoverPreviewRequest) -> PreparedCoverBackground:
        """Render one private JPG preview with only verified private fonts.

        The result stays in memory. This method deliberately has no storage or
        provider write side effect, so a browser preview and the later JPG export
        use the same layout without publishing an unfinished cover.
        """
        from PIL import Image, ImageDraw

        background = self.prepare_background(request.template_id)
        with TemporaryDirectory(prefix="xw-cover-render-") as directory:
            font_paths = self._materialize_fonts(Path(directory))
            image = Image.open(io.BytesIO(background.content)).convert("RGB")
            draw = ImageDraw.Draw(image)
            self._draw_fitted(draw, image, "composer", request.composer, font_paths)
            self._draw_fitted(draw, image, "title", request.title, font_paths)
            self._draw_fitted(draw, image, "arranger", request.arranger, font_paths)
            self._draw_fitted(draw, image, "arrangement_label", "", font_paths)
            self._draw_fitted(draw, image, "edition", request.edition, font_paths)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=95, optimize=True)
        return PreparedCoverBackground(
            content=output.getvalue(), mime_type="image/jpeg", width=image.width, height=image.height,
            template=background.template,
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

    def _materialize_fonts(self, directory: Path) -> dict[str, Path]:
        from PIL import ImageFont

        paths: dict[str, Path] = {}
        for item in self._client.list_children(self._font_folder_id):
            if item.is_folder or Path(item.name).suffix.casefold() not in _FONT_EXTENSIONS:
                continue
            path = directory / item.name
            path.write_bytes(self._client.download(item.drive_id, item.item_id))
            try:
                family, _style = ImageFont.truetype(str(path), size=16).getname()
            except Exception as exc:  # noqa: BLE001
                raise CoverConfigurationError(f"Private font '{item.name}' cannot be loaded") from exc
            if family:
                paths[str(family).strip().casefold()] = path
        missing = [family for family in self._spec.required_families if family.casefold() not in paths]
        if missing:
            raise CoverConfigurationError(f"Cover export blocked: missing font {', '.join(missing)}")
        return paths

    def _draw_fitted(self, draw: object, image: object, key: str, value: str, font_paths: dict[str, Path]) -> None:
        style = self._spec.styles[key]
        box = self._spec.boxes[key]
        text = str(style.get("text") or value or "").strip()
        if not text:
            return
        family = str(style["family"]).casefold()
        base_size = float(style["size_pt"]) * 96 / 72 * image.height / 1000
        x, y, width, height = (round(box[0] * image.width), round(box[1] * image.height),
                               round(box[2] * image.width), round(box[3] * image.height))
        if key == "title":
            lines = _title_lines(text, draw, font_paths[family], base_size, width, height, style)
            proposed = style.get("proposed_size_pt_by_lines")
            if isinstance(proposed, dict):
                base_size = float(proposed.get(len(lines), style["size_pt"])) * 96 / 72 * image.height / 1000
        else:
            lines = [text.upper() if style.get("small_caps") else text]
            if style.get("small_caps"):
                # The commercial face is loaded from private storage.  If it has
                # no OpenType small-caps feature, this documented glyph-size
                # treatment is the controlled fallback from COVER_SPEC.
                base_size *= 0.78
        min_size = max(7, round(base_size * (0.78 if style.get("small_caps") else 0.55)))
        font = _fit_font(draw, lines, font_paths[family], base_size, width, height, min_size)
        rendered = "\n".join(lines)
        spacing = max(1, round(font.size * 0.08))
        bbox = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing, align="center")
        text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if text_width > width or text_height > height:
            raise CoverConfigurationError(f"{key} does not fit the configured cover box")
        target_x = x + (width - text_width) / 2 - bbox[0]
        target_y = y + (height - text_height) / 2 - bbox[1]
        draw.multiline_text((target_x, target_y), rendered, font=font, fill=str(style["color"]), spacing=spacing, align="center")
        if style.get("underline"):
            line_y = target_y + text_height + 1
            draw.line((target_x, line_y, target_x + text_width, line_y), fill=str(style["color"]), width=1)


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
    raw_boxes = template.get("boxes")
    if not isinstance(raw_boxes, dict):
        raise CoverConfigurationError("COVER_SPEC is missing template boxes")
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
    boxes: dict[str, tuple[float, float, float, float]] = {}
    required_boxes = ("composer", "title", "arrangement_label", "arranger", "edition")
    for key in required_boxes:
        raw_box = raw_boxes.get(key)
        if (
            not isinstance(raw_box, list) or len(raw_box) != 4
            or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in raw_box)
            or raw_box[2] <= 0 or raw_box[3] <= 0
            or raw_box[0] + raw_box[2] > 1 or raw_box[1] + raw_box[3] > 1
        ):
            raise CoverConfigurationError(f"COVER_SPEC has an invalid {key} box")
        boxes[key] = tuple(float(value) for value in raw_box)
    normalized_styles: dict[str, dict[str, object]] = {}
    for key in required_boxes:
        style = styles.get(key)
        if not isinstance(style, dict) or not isinstance(style.get("family"), str) or not isinstance(style.get("size_pt"), (int, float)) or not isinstance(style.get("color"), str):
            raise CoverConfigurationError(f"COVER_SPEC has an invalid {key} text style")
        normalized_styles[key] = style
    return CoverRenderSpec(
        source_width_px=source_size[0],
        source_height_px=source_size[1],
        output_height_px=output_height,
        output_format=output_format,
        preserve_aspect_ratio=True,
        required_families=tuple(required_families),
        boxes=boxes,
        styles=normalized_styles,
    )


def _fit_font(draw: object, lines: list[str], font_path: Path, start_size: float, max_width: int, max_height: int, min_size: int):
    from PIL import ImageFont

    for size in range(max(round(start_size), min_size), min_size - 1, -1):
        font = ImageFont.truetype(str(font_path), size=size)
        bbox = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=max(1, round(size * 0.08)), align="center")
        if bbox[2] - bbox[0] <= max_width and bbox[3] - bbox[1] <= max_height:
            return font
    return ImageFont.truetype(str(font_path), size=min_size)


def _title_lines(text: str, draw: object, font_path: Path, base_size: float, width: int, height: int, style: dict[str, object]) -> list[str]:
    manual = [line.strip() for line in text.splitlines() if line.strip()]
    if len(manual) > 1:
        if len(manual) > 3:
            raise CoverConfigurationError("Title supports at most three manual lines")
        return manual
    clean = " ".join(text.split())
    words = clean.split()
    if not words:
        return [""]
    proposed = style.get("proposed_size_pt_by_lines")
    for count in range(1, 4):
        candidates = _wrap_words(words, count)
        size_pt = float(proposed.get(count, style["size_pt"])) if isinstance(proposed, dict) else float(style["size_pt"])
        font = _fit_font(draw, candidates, font_path, size_pt * 96 / 72, width, height, max(8, round(float(style.get("minimum_size_pt_proposed", 18)) * 96 / 72)))
        bbox = draw.multiline_textbbox((0, 0), "\n".join(candidates), font=font, spacing=max(1, round(font.size * 0.08)), align="center")
        if bbox[2] - bbox[0] <= width and bbox[3] - bbox[1] <= height:
            return candidates
    raise CoverConfigurationError("Title does not fit in three cover lines")


def _wrap_words(words: list[str], count: int) -> list[str]:
    if count == 1:
        return [" ".join(words)]
    lines = [""] * count
    for word in words:
        target = min(range(count), key=lambda index: len(lines[index]))
        lines[target] = f"{lines[target]} {word}".strip()
    return [line for line in lines if line]
