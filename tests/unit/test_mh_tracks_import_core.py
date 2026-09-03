from __future__ import annotations

from xw_office.services.filename_generator.mh_tracks_import_core import (
    build_mh_tracks_import_plan,
    parse_mh_tracks_audio_file_name,
)


def test_parse_recognizes_four_part_filename() -> None:
    parsed = parse_mh_tracks_audio_file_name("sk-t__03__btb__teacher -- Ein Titel.mp3")

    assert parsed.recognized
    assert parsed.valid
    assert parsed.edition_slug == "sk-t"
    assert parsed.track_number == "03"
    assert parsed.group == "btb"
    assert parsed.role == "teacher"
    assert parsed.title == "Ein Titel"
    assert parsed.track_key == "sk-t::03"


def test_parse_ignores_non_mp3_and_unstructured_names() -> None:
    assert not parse_mh_tracks_audio_file_name("readme.txt").recognized
    assert not parse_mh_tracks_audio_file_name("random name.mp3").recognized


def test_plan_replaces_audio_for_existing_stem() -> None:
    files = [{"originalFileName": "sk-t__03__btb__practice.mp3", "fileUrl": "wix:audio://new"}]
    tracks = [
        {
            "_id": "track-1",
            "trackKey": "sk-t::03",
            "editionSlug": "sk-t",
            "trackNumber": "03",
            "stems": [{"id": "btb-practice", "group": "btb", "role": "practice", "audioUrl": "wix:audio://old"}],
        }
    ]

    plan = build_mh_tracks_import_plan(files=files, tracks=tracks, editions=[{"editionSlug": "sk-t"}])

    assert plan.can_apply
    assert plan.summary["updates"] == 1
    assert plan.summary["inserts"] == 0
    assert plan.writes[0]["stems"][0]["audioUrl"] == "wix:audio://new"


def test_plan_creates_new_track_draft_when_title_present() -> None:
    files = [{"originalFileName": "sk-t__05__btb__practice -- Neuer Track.mp3", "fileUrl": "wix:audio://x"}]
    tracks = [
        {
            "_id": "track-1",
            "trackKey": "sk-t::03",
            "editionSlug": "sk-t",
            "trackNumber": "03",
            "stems": [{"id": "btb-practice", "group": "btb", "role": "practice", "audioUrl": "wix:audio://old"}],
        }
    ]

    plan = build_mh_tracks_import_plan(files=files, tracks=tracks, editions=[{"editionSlug": "sk-t"}])

    assert plan.can_apply
    assert plan.summary["inserts"] == 1
    new_track = next(track for track in plan.writes if not track.get("_id"))
    assert new_track["trackKey"] == "sk-t::05"
    assert new_track["visible"] is False


def test_plan_errors_when_new_track_missing_title() -> None:
    files = [{"originalFileName": "sk-t__05__btb__practice.mp3", "fileUrl": "wix:audio://x"}]

    plan = build_mh_tracks_import_plan(files=files, tracks=[], editions=[{"editionSlug": "sk-t"}])

    assert not plan.can_apply
    assert plan.errors


def test_plan_is_stable_and_unchanged_when_nothing_differs() -> None:
    files = [{"originalFileName": "sk-t__03__btb__practice.mp3", "fileUrl": "wix:audio://same"}]
    tracks = [
        {
            "_id": "track-1",
            "trackKey": "sk-t::03",
            "editionSlug": "sk-t",
            "trackNumber": "03",
            "stems": [{"id": "btb-practice", "group": "btb", "role": "practice", "audioUrl": "wix:audio://same"}],
        }
    ]

    plan = build_mh_tracks_import_plan(files=files, tracks=tracks, editions=[{"editionSlug": "sk-t"}])

    assert not plan.can_apply
    assert not plan.writes
    assert plan.summary["unchangedFiles"] == 1
