"""Non-destructive MH-Tracks CMS import, run directly from XW-Studio.

Replaces the public, Permissions.Admin-gated Wix upload page for the CMS
write step: preview (read-only) then apply (writes), using the same
plan/token safety net as the Velo backend module it replaces.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from xw_office.services.filename_generator.mh_tracks_import_core import (
    MhTracksImportPlan,
    build_mh_tracks_import_plan,
)
from xw_office.services.filename_generator.models import FilenameGeneratorError

if TYPE_CHECKING:
    from xw_office.services.filename_generator.wix_media_upload import WixMediaUploadService
    from xw_office.services.wix.data_client import WixDataClient

TRACK_COLLECTION_ID = "MH-Tracks"
EDITION_COLLECTION_ID = "MH-Editions"
_PLAYER_URL_BASE = "https://www.xeisworks.at/mh-player/p"


@dataclass(frozen=True)
class MhTracksCmsApplyFailure:
    track_key: str
    message: str


@dataclass(frozen=True)
class MhTracksCmsApplyResult:
    applied: bool
    inserted: int
    updated: int
    failures: tuple[MhTracksCmsApplyFailure, ...] = field(default_factory=tuple)
    first_track_url: str = ""


def _track_player_url(track: dict[str, Any]) -> str:
    edition = str(track.get("editionSlug") or "").strip()
    track_number = str(track.get("trackNumber") or "").strip()
    groups = track.get("instrumentGroups") or []
    instrument = str(groups[0]).strip() if groups else ""
    if not edition or not instrument or not track_number.isdigit():
        return ""
    return f"{_PLAYER_URL_BASE}?e={edition}&i={instrument}&t={int(track_number)}"


class MhTracksCmsImportService:
    """Loads files + CMS state, builds a plan, and (on confirmation) writes it."""

    def __init__(self, media_service: WixMediaUploadService, data_client: WixDataClient) -> None:
        self._media = media_service
        self._data = data_client

    @property
    def is_configured(self) -> bool:
        return self._media.is_configured and self._data.is_configured

    def _load_plan(self, wix_folder_path: str) -> MhTracksImportPlan:
        _folder, raw_files = self._media.list_folder_files(wix_folder_path)
        files: list[dict[str, Any]] = [
            {
                "originalFileName": str(item.get("displayName") or item.get("originalFileName") or ""),
                "fileUrl": str(item.get("url") or item.get("fileUrl") or ""),
            }
            for item in raw_files
        ]
        tracks = self._data.query_all_items(TRACK_COLLECTION_ID)
        editions = self._data.query_all_items(EDITION_COLLECTION_ID)
        return build_mh_tracks_import_plan(files=files, tracks=tracks, editions=editions)

    def preview(self, wix_folder_path: str) -> MhTracksImportPlan:
        if not str(wix_folder_path or "").strip():
            raise FilenameGeneratorError("Bitte einen Wix-Medienordner angeben.")
        return self._load_plan(wix_folder_path)

    def apply(self, wix_folder_path: str, expected_token: str) -> MhTracksCmsApplyResult:
        token = str(expected_token or "").strip()
        if not token:
            raise FilenameGeneratorError("Die Vorschau-Bestätigung fehlt. Bitte erneut prüfen.")

        # Re-read files and CMS rows immediately before writing, exactly like the
        # replaced Velo module — the token becomes invalid if either side changed.
        plan = self._load_plan(wix_folder_path)
        if plan.token != token:
            raise FilenameGeneratorError(
                "Dateien oder CMS-Daten wurden seit der Vorschau geändert. "
                "Es wurde nichts gespeichert; bitte die Vorschau erneut öffnen."
            )
        if plan.errors:
            raise FilenameGeneratorError(f"Import abgebrochen: {' | '.join(plan.errors)}")
        if not plan.writes:
            return MhTracksCmsApplyResult(applied=True, inserted=0, updated=0)

        inserted = 0
        updated = 0
        failures: list[MhTracksCmsApplyFailure] = []
        first_track_url = ""
        for track in plan.writes:
            track_id = str(track.get("_id") or "").strip()
            data = {key: value for key, value in track.items() if key != "_id"}
            try:
                if track_id:
                    self._data.update_item(TRACK_COLLECTION_ID, track_id, data)
                    updated += 1
                else:
                    self._data.insert_item(TRACK_COLLECTION_ID, data)
                    inserted += 1
                if not first_track_url:
                    first_track_url = _track_player_url(track)
            except FilenameGeneratorError as exc:
                failures.append(MhTracksCmsApplyFailure(str(track.get("trackKey") or ""), str(exc)))

        return MhTracksCmsApplyResult(
            applied=not failures,
            inserted=inserted,
            updated=updated,
            failures=tuple(failures),
            first_track_url=first_track_url,
        )
