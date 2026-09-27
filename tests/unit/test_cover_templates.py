import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from xw_office.services.product_hub.cover_templates import (
    CoverConfigurationError,
    CoverTemplateService,
)
from xw_office.services.product_hub.onedrive import OneDriveItem
from xw_office.web.routers.covers import build_covers_router


class _Client:
    root_drive_id = "drive"

    def __init__(self, *, image_size: tuple[int, int] = (746, 1000)) -> None:
        image = Image.new("RGB", image_size, (19, 71, 143))
        output = io.BytesIO()
        image.save(output, format="PNG")
        self._image = output.getvalue()

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
        return []

    def download(self, drive_id: str, item_id: str) -> bytes:
        if drive_id == "drive" and item_id == "cover":
            return self._image
        raise AssertionError("No font download is expected in this test")


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


def test_font_readiness_explains_missing_private_fonts() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")

    result = service.font_readiness()
    assert result.export_ready is False
    assert result.missing_families == ("Book Antiqua", "Deneane")


def test_cover_routes_expose_only_private_thumbnails_and_safe_configuration() -> None:
    service = CoverTemplateService(_Client(), template_folder_id="templates", font_folder_id="fonts")
    app = FastAPI()
    app.include_router(build_covers_router(lambda: service))
    client = TestClient(app)

    configuration = client.get("/api/v1/covers/configuration")
    assert configuration.status_code == 200
    assert configuration.json()["output_height_px"] == 1000
    assert configuration.json()["required_families"] == ["Book Antiqua", "Deneane"]

    thumbnail = client.get("/api/v1/covers/templates/cover/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert thumbnail.headers["cache-control"] == "private, no-store"
    assert thumbnail.content[:2] == b"\xff\xd8"
