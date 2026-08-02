from __future__ import annotations

from pathlib import Path

import pytest

from xw_office.services.qr_codes.models import (
    QrBatchRequest,
    QrOutputError,
    QrRecord,
    QrRenderSettings,
)
from xw_office.services.qr_codes.presets import (
    WHOLE_SCALE,
    build_numeric_records,
    default_numeric_form,
    get_preset,
)
from xw_office.services.qr_codes.service import QrCodeService


class _FakeSettingsRepo:
    """In-memory stand-in for SettingKvRepository (same duck-typed shape)."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_value_json(self, key: str) -> str | None:
        return self._store.get(key)

    def set_value_json(self, key: str, value_json: str) -> None:
        self._store[key] = value_json


def _sample_records(n: int = 3) -> tuple[QrRecord, ...]:
    return tuple(
        QrRecord(
            ordinal=i,
            source_key=f"{i:02d}",
            logical_id=f"TEST-{i:02d}",
            payload_url=f"https://example.test/{i:02d}",
            output_filename=f"TEST_{i:02d}.png",
        )
        for i in range(1, n + 1)
    )


def test_load_settings_without_repo_returns_defaults() -> None:
    service = QrCodeService(settings_repo=None)

    settings = service.load_settings()

    assert settings == QrRenderSettings()


def test_save_and_load_settings_roundtrip_with_fake_repo() -> None:
    repo = _FakeSettingsRepo()
    service = QrCodeService(settings_repo=repo)

    custom = QrRenderSettings(width_px=800, height_px=800, logo_enabled=False, collision_policy="rename")
    service.save_settings(custom)
    loaded = service.load_settings()

    assert loaded == custom


def test_load_settings_ignores_unknown_keys_and_missing_fields() -> None:
    repo = _FakeSettingsRepo()
    repo.set_value_json("qr_codes.settings", '{"width_px": 500, "unknown_field": "x"}')
    service = QrCodeService(settings_repo=repo)

    loaded = service.load_settings()

    assert loaded.width_px == 500
    assert loaded.height_px == QrRenderSettings().height_px


def test_precheck_records_flags_duplicate_filenames(tmp_path: Path) -> None:
    service = QrCodeService()
    records = (
        QrRecord(1, "a", "A", "https://example.test/a", "same.png"),
        QrRecord(2, "b", "B", "https://example.test/b", "same.png"),
    )

    annotated = service.precheck_records(records, tmp_path)

    assert annotated[0].warning == ""
    assert "Doppelter" in annotated[1].warning


def test_precheck_records_flags_existing_files(tmp_path: Path) -> None:
    (tmp_path / "TEST_01.png").write_bytes(b"existing")
    service = QrCodeService()
    records = _sample_records(1)

    annotated = service.precheck_records(records, tmp_path)

    assert "existiert bereits" in annotated[0].warning


def test_precheck_output_directory_creates_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "output"
    service = QrCodeService()

    service.precheck_output_directory(target)

    assert target.is_dir()


def test_generate_batch_writes_pngs_and_manifest(tmp_path: Path) -> None:
    service = QrCodeService()
    preset = get_preset(WHOLE_SCALE)
    form = default_numeric_form(preset)
    form.sequence = type(form.sequence)(start=1, end=3, step=1, minimum_width=2)
    records = build_numeric_records(preset, form)

    request = QrBatchRequest(
        variant_key=WHOLE_SCALE,
        records=records,
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
    )

    seen_progress: list[tuple[int, int, str]] = []
    summary = service.generate_batch(request, progress=lambda cur, tot, name: seen_progress.append((cur, tot, name)))

    assert summary.succeeded == 3
    assert summary.failed == 0
    assert not summary.cancelled
    for record in records:
        assert (tmp_path / record.output_filename).exists()
    assert summary.manifest_path is not None
    assert summary.manifest_path.exists()
    manifest_text = summary.manifest_path.read_text(encoding="utf-8-sig")
    assert "logical_id;payload_url" in manifest_text
    assert len(seen_progress) == 3
    assert seen_progress[0] == (1, 3, records[0].logical_id)


def test_generate_batch_aborts_entirely_on_collision_by_default(tmp_path: Path) -> None:
    (tmp_path / "TEST_01.png").write_bytes(b"existing")
    service = QrCodeService()
    request = QrBatchRequest(
        variant_key="test",
        records=_sample_records(2),
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
        collision_policy="abort",
    )

    with pytest.raises(QrOutputError):
        service.generate_batch(request)

    assert not (tmp_path / "TEST_02.png").exists()


def test_generate_batch_overwrite_policy_replaces_existing_file(tmp_path: Path) -> None:
    (tmp_path / "TEST_01.png").write_bytes(b"old-content")
    service = QrCodeService()
    request = QrBatchRequest(
        variant_key="test",
        records=_sample_records(1),
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
        collision_policy="overwrite",
    )

    summary = service.generate_batch(request)

    assert summary.succeeded == 1
    assert (tmp_path / "TEST_01.png").read_bytes() != b"old-content"


def test_generate_batch_rename_policy_avoids_overwriting(tmp_path: Path) -> None:
    (tmp_path / "TEST_01.png").write_bytes(b"old-content")
    service = QrCodeService()
    request = QrBatchRequest(
        variant_key="test",
        records=_sample_records(1),
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
        collision_policy="rename",
    )

    summary = service.generate_batch(request)

    assert summary.succeeded == 1
    assert (tmp_path / "TEST_01.png").read_bytes() == b"old-content"
    assert (tmp_path / "TEST_01_2.png").exists()


def test_generate_batch_respects_cancellation(tmp_path: Path) -> None:
    service = QrCodeService()
    records = _sample_records(5)
    request = QrBatchRequest(
        variant_key="test",
        records=records,
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
    )

    summary = service.generate_batch(request, should_cancel=lambda: True)

    assert summary.cancelled is True
    assert summary.succeeded == 0


def test_generate_batch_continues_after_single_record_render_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known QrModuleError on one record is logged, and the batch continues."""
    from xw_office.services.qr_codes.models import QrRenderError

    service = QrCodeService()
    records = _sample_records(3)
    request = QrBatchRequest(
        variant_key="test",
        records=records,
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
    )

    original_render = service._renderer.render

    def flaky_render(payload: str, settings: QrRenderSettings) -> bytes:
        if "02" in payload:
            raise QrRenderError("boom")
        return original_render(payload, settings)

    monkeypatch.setattr(service._renderer, "render", flaky_render)

    summary = service.generate_batch(request)

    assert summary.succeeded == 2
    assert summary.failed == 1
    failed_result = next(r for r in summary.results if not r.success)
    assert failed_result.record.source_key == "02"
    assert "boom" in failed_result.error_message


def test_generate_batch_propagates_unexpected_errors_instead_of_swallowing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unanticipated bug (not a QrModuleError/OSError) must not be silently swallowed."""
    service = QrCodeService()
    records = _sample_records(3)
    request = QrBatchRequest(
        variant_key="test",
        records=records,
        output_directory=tmp_path,
        render_settings=QrRenderSettings(logo_enabled=False),
    )

    def broken_render(payload: str, settings: QrRenderSettings) -> bytes:
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(service._renderer, "render", broken_render)

    with pytest.raises(RuntimeError):
        service.generate_batch(request)
