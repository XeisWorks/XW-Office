from __future__ import annotations

import pytest

from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameGeneratorRequest,
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
