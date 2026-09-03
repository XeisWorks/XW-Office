from __future__ import annotations

import pytest

from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameGeneratorRequest,
    FilenameRenameOperation,
    FilenameRenameRules,
)
from xw_office.services.filename_generator.service import FilenameGeneratorService


def test_build_filenames_produces_expected_starterkit_names() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="sk-t",
        instrument_slug="btb",
        track_start=1,
        track_end=3,
        roles=("practice", "teacher"),
    )

    names = svc.build_filenames(request)

    assert names == [
        "sk-t__01__btb__practice.mp3",
        "sk-t__01__btb__teacher.mp3",
        "sk-t__02__btb__practice.mp3",
        "sk-t__02__btb__teacher.mp3",
        "sk-t__03__btb__practice.mp3",
        "sk-t__03__btb__teacher.mp3",
    ]


def test_build_filenames_respects_track_width() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="ow1",
        instrument_slug="trp",
        track_start=9,
        track_end=9,
        roles=("practice",),
        track_width=3,
    )

    assert svc.build_filenames(request) == ["ow1__009__trp__practice.mp3"]


def test_build_filenames_lowercases_slugs() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="SK-T",
        instrument_slug="BTB",
        track_start=1,
        track_end=1,
        roles=("PRACTICE",),
    )

    assert svc.build_filenames(request) == ["sk-t__01__btb__practice.mp3"]


def test_build_filenames_rejects_end_before_start() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="sk-t", instrument_slug="btb", track_start=5, track_end=1, roles=("practice",)
    )

    with pytest.raises(FilenameGeneratorError):
        svc.build_filenames(request)


def test_build_filenames_rejects_empty_roles() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="sk-t", instrument_slug="btb", track_start=1, track_end=1, roles=()
    )

    with pytest.raises(FilenameGeneratorError):
        svc.build_filenames(request)


def test_build_filenames_rejects_invalid_slug() -> None:
    svc = FilenameGeneratorService()
    request = FilenameGeneratorRequest(
        edition_slug="SK T!", instrument_slug="btb", track_start=1, track_end=1, roles=("practice",)
    )

    with pytest.raises(FilenameGeneratorError):
        svc.build_filenames(request)


def test_rename_plan_recognizes_requested_starterkit_example(tmp_path) -> None:
    source = tmp_path / "03.2 Es geht Aufwärts TIEF-BTB.mp3"
    source.write_bytes(b"audio")
    svc = FilenameGeneratorService()
    rules = FilenameRenameRules(
        default_edition_slug="",
        default_instrument_slug="",
        markers_override_defaults=True,
    )

    plan = svc.build_rename_plan(tmp_path, rules)

    assert len(plan) == 1
    assert plan[0].is_safe
    assert plan[0].target_name == "sk-t__03__btb__teacher.mp3"
    assert plan[0].title == "Es geht Aufwärts"


def test_rename_plan_keeps_cleaned_title_when_requested(tmp_path) -> None:
    (tmp_path / "3.1 Mein Lied TIEF-BTB.mp3").write_bytes(b"audio")
    svc = FilenameGeneratorService()

    plan = svc.build_rename_plan(
        tmp_path,
        FilenameRenameRules(
            default_edition_slug="sk-t",
            default_instrument_slug="btb",
            keep_title=True,
        ),
    )

    assert plan[0].target_name == "sk-t__03__btb__practice -- Mein Lied.mp3"


def test_fixed_preset_blocks_conflicting_marker(tmp_path) -> None:
    (tmp_path / "01.1 Test HOCH-BTB.mp3").write_bytes(b"audio")
    svc = FilenameGeneratorService()

    plan = svc.build_rename_plan(
        tmp_path,
        FilenameRenameRules(default_edition_slug="sk-t", default_instrument_slug="btb"),
    )

    assert plan[0].status == "review"
    assert "Preset erwartet" in plan[0].message


def test_unmapped_variant_requires_review(tmp_path) -> None:
    (tmp_path / "01.3 Langsam TIEF-BTB.mp3").write_bytes(b"audio")
    svc = FilenameGeneratorService()

    plan = svc.build_rename_plan(
        tmp_path,
        FilenameRenameRules(default_edition_slug="sk-t", default_instrument_slug="btb"),
    )

    assert plan[0].status == "review"
    assert "Variante .3" in plan[0].message


def test_rename_plan_blocks_duplicate_targets(tmp_path) -> None:
    (tmp_path / "01.1 Lied A TIEF-BTB.mp3").write_bytes(b"a")
    (tmp_path / "01.1 Lied B TIEF-BTB.mp3").write_bytes(b"b")
    svc = FilenameGeneratorService()

    plan = svc.build_rename_plan(
        tmp_path,
        FilenameRenameRules(default_edition_slug="sk-t", default_instrument_slug="btb"),
    )

    assert {item.status for item in plan} == {"conflict"}


def test_rename_plan_blocks_existing_canonical_target(tmp_path) -> None:
    (tmp_path / "01.1 Lied TIEF-BTB.mp3").write_bytes(b"legacy")
    (tmp_path / "sk-t__01__btb__practice.mp3").write_bytes(b"existing")
    svc = FilenameGeneratorService()

    plan = svc.build_rename_plan(
        tmp_path,
        FilenameRenameRules(default_edition_slug="sk-t", default_instrument_slug="btb"),
    )

    legacy = next(item for item in plan if item.source_path.name.startswith("01.1"))
    assert legacy.status == "conflict"
    assert "existiert bereits" in legacy.message


def test_execute_and_undo_rename_round_trip(tmp_path) -> None:
    source = tmp_path / "03.2 Es geht Aufwärts TIEF-BTB.mp3"
    source.write_bytes(b"audio-content")
    target_name = "sk-t__03__btb__teacher.mp3"
    svc = FilenameGeneratorService()

    result = svc.execute_rename(
        tmp_path,
        [FilenameRenameOperation(source_path=source, target_name=target_name)],
    )

    assert len(result.operations) == 1
    assert not source.exists()
    assert (tmp_path / target_name).read_bytes() == b"audio-content"
    assert svc.can_undo_last_rename

    svc.undo_last_rename()

    assert source.read_bytes() == b"audio-content"
    assert not (tmp_path / target_name).exists()
    assert not svc.can_undo_last_rename


def test_execute_never_overwrites_existing_target(tmp_path) -> None:
    source = tmp_path / "01.1 Lied.mp3"
    target = tmp_path / "sk-t__01__btb__practice.mp3"
    source.write_bytes(b"source")
    target.write_bytes(b"keep")
    svc = FilenameGeneratorService()

    with pytest.raises(FilenameGeneratorError, match="existiert bereits"):
        svc.execute_rename(
            tmp_path,
            [FilenameRenameOperation(source_path=source, target_name=target.name)],
        )

    assert source.read_bytes() == b"source"
    assert target.read_bytes() == b"keep"


def test_mapping_parser_rejects_ambiguous_source() -> None:
    svc = FilenameGeneratorService()

    with pytest.raises(FilenameGeneratorError, match="mehrfach"):
        svc.parse_mapping("2=teacher, 2=duet", field_name="Varianten")
