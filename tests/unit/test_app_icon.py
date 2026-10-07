from __future__ import annotations

from io import BytesIO
from struct import pack, unpack_from

from PIL import Image

from xw_office.core.app_paths import app_icon_path


def test_app_icon_has_green_mark_at_common_windows_sizes() -> None:
    icon_data = app_icon_path().read_bytes()
    reserved, icon_type, count = unpack_from("<HHH", icon_data)
    assert (reserved, icon_type, count) == (0, 1, 7)

    entries: list[tuple[int, int, int, int, int]] = []
    for index in range(count):
        width, height, _, _, _, bit_depth, byte_count, image_offset = unpack_from(
            "<BBBBHHII", icon_data, 6 + index * 16
        )
        entries.append((width or 256, height or 256, bit_depth, byte_count, image_offset))

    assert {(width, height) for width, height, _, _, _ in entries} == {
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256),
    }

    _, _, bit_depth, byte_count, image_offset = next(
        entry for entry in entries if entry[:2] == (32, 32)
    )
    single_frame = (
        pack("<HHH", 0, 1, 1)
        + pack("<BBBBHHII", 32, 32, 0, 0, 1, bit_depth, byte_count, 22)
        + icon_data[image_offset : image_offset + byte_count]
    )
    with Image.open(BytesIO(single_frame)) as frame_image:
        frame = frame_image.convert("RGBA")
        pixels = frame.tobytes()
    green_pixels = sum(
        1
        for offset in range(0, len(pixels), 4)
        if pixels[offset + 3] > 0
        and pixels[offset + 1] > pixels[offset] * 1.2
        and pixels[offset + 1] > pixels[offset + 2] * 1.2
    )
    assert green_pixels > 20
