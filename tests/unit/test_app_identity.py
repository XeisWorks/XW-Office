from __future__ import annotations

import pytest

from xw_office.core.app_paths import (
    APP_USER_MODEL_ID,
    DEBUG_APP_USER_MODEL_ID,
    office_app_user_model_id,
)


@pytest.mark.parametrize("start_mode", ["gui", "console", ""])
def test_normal_launch_uses_office_taskbar_identity(start_mode: str) -> None:
    assert office_app_user_model_id(start_mode) == APP_USER_MODEL_ID


def test_debug_launch_has_separate_taskbar_identity() -> None:
    assert office_app_user_model_id("debug") == DEBUG_APP_USER_MODEL_ID
    assert DEBUG_APP_USER_MODEL_ID != APP_USER_MODEL_ID
