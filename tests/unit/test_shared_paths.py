"""Shared path resolution tests."""
from pathlib import Path

from xw_office.core.shared_paths import resolve_shared_path


def test_resolve_shared_path_maps_other_windows_profile(
    tmp_path: Path,
    monkeypatch,
) -> None:
    one_drive = tmp_path / "OneDrive - XeisWorks"
    expected = one_drive / "Druckdaten" / "Titel.pdf"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"%PDF")
    monkeypatch.setenv("OneDriveCommercial", str(one_drive))

    resolved = resolve_shared_path(
        r"C:\Users\OtherUser\OneDrive - XeisWorks\Druckdaten\Titel.pdf"
    )

    assert Path(resolved) == expected


def test_resolve_shared_path_keeps_unavailable_original(monkeypatch) -> None:
    monkeypatch.delenv("OneDriveCommercial", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("OneDrive", raising=False)
    original = r"C:\Users\OtherUser\OneDrive - XeisWorks\Druckdaten\Fehlt.pdf"

    assert resolve_shared_path(original) == original
