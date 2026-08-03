from __future__ import annotations

import gc
import weakref

from xw_office.app import _retain_main_window


class _ApplicationStub:
    pass


class _WindowStub:
    pass


def test_application_retains_top_level_window_across_garbage_collection() -> None:
    app = _ApplicationStub()
    window = _WindowStub()
    window_ref = weakref.ref(window)

    _retain_main_window(app, window)  # type: ignore[arg-type]
    del window
    gc.collect()

    assert window_ref() is not None
    assert app._xw_main_window is window_ref()  # type: ignore[attr-defined]
