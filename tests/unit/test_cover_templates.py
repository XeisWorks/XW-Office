import io
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from xw_office.services.product_hub.cover_templates import (
    CoverConfigurationError,
    CoverPreviewRequest,
    CoverTemplateService,
    _configured_folder_id,
)
from xw_office.services.product_hub.onedrive import OneDriveItem
from xw_office.web.routers.covers import build_covers_router


class _Client:
    root_drive_id = "drive"

    def __init__(self, *, image_size: tuple[int, int] = (746, 1000), font: bytes | None = None) -> None:
        image = Image.new("RGB", image_size, (19, 71, 143))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self._image = output.getvalue()
        self._font = font

    def assert_within_root(self, drive_id: str, item_id: str) -> None:
        if drive_id != "drive" or item_id not in {"templates", "fonts"}:
            raise ValueError("outside root")

    def list_children(self, item_id: str):
        if item_id == "templates":
            return [
                OneDriveItem("drive", "cover", "Cover.jpg", "etag", len(self._image)),
                OneDriveItem("drive", "notes", "readme.txt", "etag", 10),
                OneDriveItem("drive", "folder", "nested", "etag", 0, is_folder=True),
            ]
        if self._font is None:
            return []
        return [OneDriveItem("drive", "font", "arial.ttf", "etag-font", len(self._font))]

    def download(self, drive_id: str, item_id: str) -> bytes:
        if drive_id == "drive" and item_id == "cover":
            return self._image
        if drive_id == "drive" and item_id == "font" and self._font is not None:
            return self._font
        raise AssertionError("No font download is expected in this test")


def _test_spec(tmp_path: Path) -> Path:
    path = tmp_path / "cover-spec.yaml"
    path.write_text(
        """template:
  source_size_px: [746, 1000]
  output_height_px: 1000
  format: jpg
  draw_card: false
  draw_shadow: false
  draw_black_bar: false
  preserve_aspect_ratio: true
  boxes:
    composer: [0.1, 0.1, 0.6, 0.06]
    title: [0.1, 0.2, 0.6, 0.25]
    arrangement_label: [0.1, 0.5, 0.6, 0.06]
    arranger: [0.1, 0.57, 0.6, 0.06]
    edition: [0.1, 0.65, 0.6, 0.06]
text_styles:
  composer: {family: Arial, size_pt: 14, color: '#222222'}
  title: {family: Arial, size_pt: 36, color: '#000000', proposed_size_pt_by_lines: {1: 36, 2: 31, 3: 26}, minimum_size_pt_proposed: 18}
  arrangement_label: {text: 'Arrangement:', family: Arial, size_pt: 12, color: '#222222', small_caps: true, underline: true}
  arranger: {family: Arial, size_pt: 12, color: '#222222'}
  edition: {family: Arial, size_pt: 12, color: '#ffffff', small_caps: true}
""",
        encoding="utf-8",
    )
    return path


def test_template_listing_only_returns_supported_image_files() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    assert [(item.item_id, item.name) for item in service.list_templates()] == [("cover", "Cover.jpg")]


def test_cover_spec_is_loaded_and_background_is_only_scaled() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    prepared = service.prepare_background("cover")

    assert (prepared.width, prepared.height) == (746, 1000)
    assert prepared.mime_type == "image/jpeg"
    with Image.open(io.BytesIO(prepared.content)) as image:
        assert image.size == (746, 1000)
        assert image.getpixel((100, 100))[2] > 120


def test_thumbnail_is_derived_privately_and_template_must_be_listed() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    with Image.open(io.BytesIO(service.thumbnail("cover"))) as thumbnail:
        assert thumbnail.width <= 240
        assert thumbnail.height <= 320
    with pytest.raises(KeyError, match="configured template folder"):
        service.thumbnail("unlisted")


def test_incompatible_background_is_explained_without_stretching() -> None:
    service = CoverTemplateService(
        _Client(image_size=(1000, 1000)), template_folder_id="templates", font_folder_id="fonts"
    )

    with pytest.raises(CoverConfigurationError, match="incompatible aspect ratio"):
        service.prepare_background("cover")


def test_cover_service_requires_both_private_folder_ids() -> None:
    with pytest.raises(CoverConfigurationError, match="must be configured"):
        CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="")


def test_cover_folder_can_be_configured_by_relative_path_without_exposing_a_windows_path(monkeypatch) -> None:
    class _Resolver:
        def resolve_relative_folder(self, path: str) -> OneDriveItem:
            assert path == "02 XeisWorks/14 Schriftarten/Cover Renderer"
            return OneDriveItem("drive", "fonts", "Cover Renderer", "etag", 0, is_folder=True)

    monkeypatch.delenv("XW_COVER_FONT_FOLDER_ID", raising=False)
    monkeypatch.setenv("XW_COVER_FONT_FOLDER_PATH", "02 XeisWorks/14 Schriftarten/Cover Renderer")
    assert _configured_folder_id(_Resolver(), "XW_COVER_FONT_FOLDER_ID", "XW_COVER_FONT_FOLDER_PATH") == "fonts"


def test_font_readiness_explains_missing_private_fonts() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    result = service.font_readiness()
    assert result.export_ready is False
    assert result.missing_families == ("Bookman Old Style", "Deneane")


def test_preview_fails_closed_without_the_private_fonts() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    with pytest.raises(CoverConfigurationError, match="missing font"):
        service.render_preview(CoverPreviewRequest(template_id="cover", title="Cabernet Polka"))


def test_preview_uses_verified_runtime_font_and_preserves_background(tmp_path: Path) -> None:
    font_path = Path(os.environ.get("WINDIR", r"C:\\Windows")) / "Fonts" / "arial.ttf"
    if not font_path.exists():
        pytest.skip("No local test font is available")
    service = CoverTemplateService(
        _Client(font=font_path.read_bytes()),
        template_folder_id="templates",
        font_folder_id="fonts",
        spec_path=_test_spec(tmp_path),
    )

    preview = service.render_preview(CoverPreviewRequest(
        template_id="cover", composer="Müller", title="Cabernet Polka für Blasmusik",
        arranger="O'Connor", edition="Partitur",
    ))

    assert (preview.width, preview.height, preview.mime_type) == (746, 1000, "image/jpeg")
    with Image.open(io.BytesIO(preview.content)) as image:
        assert image.size == (746, 1000)
        assert image.getpixel((700, 900))[2] > 120


def test_cover_routes_expose_only_private_thumbnails_and_safe_configuration() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")
    app = FastAPI()
    app.include_router(build_covers_router(lambda: service))
    client = TestClient(app)

    configuration = client.get("/api/v1/covers/configuration")
    assert configuration.status_code == 200
    assert configuration.json()["output_height_px"] == 1000
    assert configuration.json()["required_families"] == ["Bookman Old Style", "Deneane"]

    thumbnail = client.get("/api/v1/covers/templates/cover/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert thumbnail.headers["cache-control"] == "private, no-store"
    assert thumbnail.content[:2] == b"\xff\xd8"

    preview = client.post("/api/v1/covers/preview", json={"template_id": "cover", "title": "Cabernet"})
    assert preview.status_code == 422
    assert "missing font" in preview.json()["detail"]
