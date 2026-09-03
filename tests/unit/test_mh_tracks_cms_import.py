from __future__ import annotations

from xw_office.services.filename_generator.mh_tracks_cms_import import MhTracksCmsImportService
from xw_office.services.filename_generator.models import FilenameGeneratorError
import pytest


class _FakeMediaService:
    def __init__(self, files: list[dict]) -> None:
        self._files = files
        self.is_configured = True

    def list_folder_files(self, target_path: str):
        return object(), self._files


class _FakeDataClient:
    def __init__(self, tracks: list[dict], editions: list[dict]) -> None:
        self._tracks = tracks
        self._editions = editions
        self.is_configured = True
        self.inserted: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def query_all_items(self, collection_id: str):
        if collection_id == "MH-Tracks":
            return self._tracks
        if collection_id == "MH-Editions":
            return self._editions
        return []

    def insert_item(self, collection_id: str, data: dict) -> dict:
        self.inserted.append(data)
        return {**data, "_id": "new-id"}

    def update_item(self, collection_id: str, item_id: str, data: dict) -> dict:
        self.updated.append((item_id, data))
        return {**data, "_id": item_id}


def _tracks_fixture() -> list[dict]:
    return [
        {
            "_id": "track-1",
            "trackKey": "sk-t::03",
            "editionSlug": "sk-t",
            "trackNumber": "03",
            "stems": [{"id": "btb-practice", "group": "btb", "role": "practice", "audioUrl": "wix:audio://old"}],
        }
    ]


def test_preview_then_apply_updates_existing_track() -> None:
    media = _FakeMediaService(
        [{"displayName": "sk-t__03__btb__practice.mp3", "url": "wix:audio://new"}]
    )
    data = _FakeDataClient(_tracks_fixture(), [{"editionSlug": "sk-t"}])
    service = MhTracksCmsImportService(media, data)  # type: ignore[arg-type]

    plan = service.preview("/MH-Tracks/sk-t/btb/uploads/x")
    assert plan.can_apply

    result = service.apply("/MH-Tracks/sk-t/btb/uploads/x", plan.token)
    assert result.applied
    assert result.updated == 1
    assert data.updated[0][0] == "track-1"


def test_apply_rejects_stale_token() -> None:
    media = _FakeMediaService(
        [{"displayName": "sk-t__03__btb__practice.mp3", "url": "wix:audio://new"}]
    )
    data = _FakeDataClient(_tracks_fixture(), [{"editionSlug": "sk-t"}])
    service = MhTracksCmsImportService(media, data)  # type: ignore[arg-type]

    with pytest.raises(FilenameGeneratorError, match="ge\u00e4ndert"):
        service.apply("/MH-Tracks/sk-t/btb/uploads/x", "stale-token")
