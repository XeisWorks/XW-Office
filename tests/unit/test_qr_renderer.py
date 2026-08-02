from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from xw_office.services.qr_codes.models import QrRenderError, QrRenderSettings
from xw_office.services.qr_codes.renderer import SegnoLogoQrRenderer

PAYLOAD = "https://www.xeisworks.at/mh-player/p?e=uuu2&i=pos&t=1"


def _decode(png_bytes: bytes) -> str:
    import cv2
    import numpy as np

    array = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    payload, _points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return payload


def _settings(**overrides: object) -> QrRenderSettings:
    base = QrRenderSettings(logo_enabled=False)
    return QrRenderSettings(**{**base.__dict__, **overrides})


def test_render_produces_exact_pixel_size_png() -> None:
    renderer = SegnoLogoQrRenderer()
    png_bytes = renderer.render(PAYLOAD, _settings())

    image = Image.open(io.BytesIO(png_bytes))
    assert image.format == "PNG"
    assert image.size == (1000, 1000)


def test_render_without_logo_is_decodable() -> None:
    renderer = SegnoLogoQrRenderer()
    png_bytes = renderer.render(PAYLOAD, _settings())

    assert _decode(png_bytes) == PAYLOAD


def test_render_with_default_logo_proportions_is_decodable(tmp_path: Path) -> None:
    logo_path = tmp_path / "default-logo.png"
    Image.new("RGB", (400, 160), (10, 20, 30)).save(logo_path)

    renderer = SegnoLogoQrRenderer()
    settings = _settings(logo_enabled=True, logo_path=str(logo_path))
    png_bytes = renderer.render(PAYLOAD, settings)

    assert _decode(png_bytes) == PAYLOAD


def test_render_with_transparent_logo_is_decodable(tmp_path: Path) -> None:
    logo_path = tmp_path / "logo.png"
    logo = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for x in range(60, 140):
        for y in range(60, 140):
            logo.putpixel((x, y), (10, 20, 30, 255))
    logo.save(logo_path)

    settings = _settings(logo_enabled=True, logo_path=str(logo_path))
    renderer = SegnoLogoQrRenderer()
    png_bytes = renderer.render(PAYLOAD, settings)

    assert _decode(png_bytes) == PAYLOAD


@pytest.mark.parametrize("size", [(300, 120), (120, 300)])
def test_render_preserves_logo_aspect_ratio(tmp_path: Path, size: tuple[int, int]) -> None:
    logo_path = tmp_path / "logo.png"
    Image.new("RGB", size, (10, 20, 30)).save(logo_path)

    settings = _settings(logo_enabled=True, logo_path=str(logo_path))
    renderer = SegnoLogoQrRenderer()
    png_bytes = renderer.render(PAYLOAD, settings)

    assert _decode(png_bytes) == PAYLOAD
    image = Image.open(io.BytesIO(png_bytes))
    assert image.size == (1000, 1000)


def test_quiet_zone_stays_background_color() -> None:
    renderer = SegnoLogoQrRenderer()
    png_bytes = renderer.render(PAYLOAD, _settings())

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert image.getpixel((999, 999)) == (255, 255, 255)


def test_missing_logo_raises_render_error() -> None:
    settings = _settings(logo_enabled=True, logo_path=r"C:\does\not\exist\logo.png")
    renderer = SegnoLogoQrRenderer()

    with pytest.raises(QrRenderError):
        renderer.render(PAYLOAD, settings)


def test_render_rejects_non_positive_dimensions() -> None:
    settings = _settings(width_px=0)
    renderer = SegnoLogoQrRenderer()

    with pytest.raises(QrRenderError):
        renderer.render(PAYLOAD, settings)


def test_render_rejects_size_too_small_for_module_count() -> None:
    settings = _settings(width_px=10, height_px=10)
    renderer = SegnoLogoQrRenderer()

    with pytest.raises(QrRenderError):
        renderer.render(PAYLOAD, settings)
