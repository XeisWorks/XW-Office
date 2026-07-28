from __future__ import annotations

import pytest

from xw_studio.services.qr_codes.filename_sanitizer import sanitize_windows_filename
from xw_studio.services.qr_codes.models import QrConfigurationError


def test_replaces_windows_invalid_characters() -> None:
    assert sanitize_windows_filename("UUU#2-POS/01") == "UUU#2-POS_01"


def test_strips_trailing_dots_and_spaces() -> None:
    assert sanitize_windows_filename("name. ") == "name"


def test_collapses_repeated_replacement_characters() -> None:
    assert sanitize_windows_filename("a///b") == "a_b"


@pytest.mark.parametrize("reserved", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"])
def test_prefixes_reserved_windows_device_names(reserved: str) -> None:
    result = sanitize_windows_filename(reserved)
    assert result == f"_{reserved}"


def test_raises_when_result_would_be_empty() -> None:
    with pytest.raises(QrConfigurationError):
        sanitize_windows_filename("...")
