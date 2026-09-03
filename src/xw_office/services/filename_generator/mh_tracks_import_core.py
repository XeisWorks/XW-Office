"""Pure planner for the MH-Tracks audio import.

Python port of the Wix Velo module ``mhTracksImportCore.js`` so the same
non-destructive import logic can run directly in XW-Studio instead of the
public, permission-gated Wix upload page. Keep this in sync with the Velo
original when the naming convention or write rules change.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

_AUDIO_EXTENSION = ".mp3"
_FILE_ID_SEPARATOR = "__"
_TITLE_SEPARATOR = " -- "

_ROLE_LABELS = {
    "practice": "ÜBEN",
    "performance": "VORSPIEL",
    "teacher": "DUETT",
    "voice": "STIMME",
    "mix": "GESAMT",
}

_SAFE_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_DIGITS_RE = re.compile(r"^\d+$")
_NATURAL_CHUNK_RE = re.compile(r"(\d+)")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _slug(value: Any) -> str:
    return _text(value).lower()


def _normalized_track_number(value: Any) -> str:
    raw = _text(value)
    if not _DIGITS_RE.match(raw) or int(raw) < 1:
        return ""
    return str(int(raw)).zfill(2)


def _safe_token(value: Any) -> str:
    normalized = _slug(value)
    return normalized if _SAFE_TOKEN_RE.match(normalized) else ""


def _stem_identity(group: str, role: str, register_role: str = "") -> str:
    return "::".join(part for part in (group, role, register_role) if part)


def _stem_id(group: str, role: str, register_role: str = "") -> str:
    return "-".join(part for part in (group, register_role, role) if part)


def _natural_sort_key(value: str) -> list[Any]:
    return [int(chunk) if chunk.isdigit() else chunk.lower() for chunk in _NATURAL_CHUNK_RE.split(value or "")]


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ParsedAudioFile:
    recognized: bool
    valid: bool
    file_name: str
    error: str = ""
    edition_slug: str = ""
    track_number: str = ""
    track_key: str = ""
    group: str = ""
    role: str = ""
    register_role: str = ""
    title: str = ""
    stem_identity: str = ""
    stem_id: str = ""
    import_key: str = ""
    file_url: str = ""


def parse_mh_tracks_audio_file_name(original_file_name: Any) -> ParsedAudioFile:
    file_name = _text(original_file_name)
    if not file_name.lower().endswith(_AUDIO_EXTENSION):
        return ParsedAudioFile(recognized=False, valid=False, file_name=file_name)

    base_name = file_name[: -len(_AUDIO_EXTENSION)]
    title_separator_index = base_name.find(_TITLE_SEPARATOR)
    if title_separator_index >= 0:
        identity_part = base_name[:title_separator_index].strip()
        title = base_name[title_separator_index + len(_TITLE_SEPARATOR) :].strip()
    else:
        identity_part = base_name.strip()
        title = ""

    if _FILE_ID_SEPARATOR not in identity_part:
        return ParsedAudioFile(recognized=False, valid=False, file_name=file_name)

    parts = [part.strip() for part in identity_part.split(_FILE_ID_SEPARATOR)]
    if len(parts) not in (4, 5):
        return ParsedAudioFile(
            recognized=True,
            valid=False,
            file_name=file_name,
            error='Erwartet werden 4 oder 5 mit "__" getrennte Angaben.',
        )

    raw_edition_slug, raw_track_number, raw_group, raw_role = parts[:4]
    raw_register_role = parts[4] if len(parts) == 5 else ""
    edition_slug = _safe_token(raw_edition_slug)
    track_number = _normalized_track_number(raw_track_number)
    group = _safe_token(raw_group)
    role = _safe_token(raw_role)
    register_role = _safe_token(raw_register_role) if raw_register_role else ""

    if not edition_slug:
        return ParsedAudioFile(recognized=True, valid=False, file_name=file_name, error="Der Edition-Slug ist ungültig.")
    if not track_number:
        return ParsedAudioFile(
            recognized=True, valid=False, file_name=file_name, error="Die Tracknummer muss eine positive Zahl sein."
        )
    if not group:
        return ParsedAudioFile(
            recognized=True, valid=False, file_name=file_name, error="Die Instrument-/Stem-Gruppe ist ungültig."
        )
    if not role:
        return ParsedAudioFile(recognized=True, valid=False, file_name=file_name, error="Die Rolle/Version ist ungültig.")
    if raw_register_role and not register_role:
        return ParsedAudioFile(
            recognized=True, valid=False, file_name=file_name, error="Die optionale Registerrolle ist ungültig."
        )

    track_key = f"{edition_slug}::{track_number}"
    identity = _stem_identity(group, role, register_role)
    return ParsedAudioFile(
        recognized=True,
        valid=True,
        file_name=file_name,
        edition_slug=edition_slug,
        track_number=track_number,
        track_key=track_key,
        group=group,
        role=role,
        register_role=register_role,
        title=title,
        stem_identity=identity,
        stem_id=_stem_id(group, role, register_role),
        import_key=f"{track_key}::{identity}",
    )


def _normalized_stem_identity(stem: dict[str, Any]) -> str:
    return _stem_identity(_slug(stem.get("group")), _slug(stem.get("role")), _slug(stem.get("registerRole")))


def _build_default_stem(parsed: ParsedAudioFile, file_url: str, existing_stems: list[dict[str, Any]]) -> dict[str, Any]:
    same_group_count = sum(1 for stem in existing_stems if _slug(stem.get("group")) == parsed.group)
    sort_order = (same_group_count + 1) * 10
    default_enabled = parsed.role == "practice" and not any(
        _slug(stem.get("group")) == parsed.group and stem.get("defaultEnabled") for stem in existing_stems
    )
    return {
        "id": parsed.stem_id,
        "group": parsed.group,
        "role": parsed.role,
        "registerRole": parsed.register_role,
        "label": _ROLE_LABELS.get(parsed.role, parsed.role.upper()),
        "shortLabel": "",
        "altTrackTitle": "",
        "toolTip": "",
        "audioUrl": file_url,
        "channels": 2,
        "defaultGainDb": 0,
        "pan": 0,
        "defaultEnabled": default_enabled,
        "required": False,
        "sortOrder": sort_order,
        "color": "",
        "icon": "",
        "pdfUrl": "",
        "sourceLegacyField": "",
    }


def _plan_fingerprint(files: list[dict[str, Any]], tracks: list[dict[str, Any]]) -> str:
    file_state = sorted(
        (
            {"name": _text(file.get("originalFileName")), "url": _text(file.get("fileUrl"))}
            for file in files
        ),
        key=lambda entry: _natural_sort_key(entry["name"]),
    )
    track_state = sorted(
        (
            {
                "id": _text(track.get("_id")),
                "updated": _text(track.get("_updatedDate")),
                "key": _text(track.get("trackKey")),
                "stems": sorted(
                    (
                        {
                            "identity": _normalized_stem_identity(stem),
                            "url": _text(stem.get("audioUrl")),
                        }
                        for stem in (track.get("stems") or [])
                        if isinstance(stem, dict)
                    ),
                    key=lambda entry: _natural_sort_key(entry["identity"]),
                ),
            }
            for track in tracks
        ),
        key=lambda entry: _natural_sort_key(entry["key"]),
    )
    return _stable_hash({"fileState": file_state, "trackState": track_state})


def _new_track_from_file(parsed: ParsedAudioFile) -> dict[str, Any]:
    return {
        "editionSlug": parsed.edition_slug,
        "trackNumber": parsed.track_number,
        "trackKey": parsed.track_key,
        "title": parsed.title,
        "composerArranger": "",
        "artist": "",
        "articleNumber": "",
        "playbackMode": "instrument-variants",
        "fallbackMixUrl": "",
        "durationSeconds": None,
        "sortOrder": int(parsed.track_number),
        "visible": False,
        "instrumentGroups": [],
        "stemCount": 0,
        "stems": [],
        "legacyNotes": "Als Entwurf über den nicht-destruktiven MH-Tracks-Audioimport angelegt.",
    }


def _finalize_track(track: dict[str, Any]) -> dict[str, Any]:
    stems = track.get("stems") or []
    finalized = dict(track)
    finalized["stems"] = stems
    finalized["instrumentGroups"] = sorted({_slug(stem.get("group")) for stem in stems if _slug(stem.get("group"))})
    finalized["stemCount"] = len(stems)
    return finalized


@dataclass
class MhTracksImportPlan:
    token: str
    files: list[ParsedAudioFile]
    actions: list[dict[str, Any]]
    writes: list[dict[str, Any]]
    errors: list[str]
    warnings: list[str]
    ignored_files: list[str]
    can_apply: bool
    summary: dict[str, int] = field(default_factory=dict)


def build_mh_tracks_import_plan(
    *,
    files: list[dict[str, Any]] | None = None,
    tracks: list[dict[str, Any]] | None = None,
    editions: list[dict[str, Any]] | None = None,
) -> MhTracksImportPlan:
    files = files or []
    tracks = tracks or []
    editions = editions or []

    errors: list[str] = []
    warnings: list[str] = []
    ignored_files: list[str] = []
    parsed_files: list[ParsedAudioFile] = []

    for file in files:
        parsed = parse_mh_tracks_audio_file_name(file.get("originalFileName"))
        if not parsed.recognized:
            ignored_files.append(_text(file.get("originalFileName")))
            continue
        if not parsed.valid:
            errors.append(f"{parsed.file_name}: {parsed.error}")
            continue
        file_url = _text(file.get("fileUrl"))
        if not file_url:
            errors.append(f"{parsed.file_name}: Die Wix-Media-URL fehlt.")
            continue
        parsed_files.append(
            ParsedAudioFile(
                recognized=parsed.recognized,
                valid=parsed.valid,
                file_name=parsed.file_name,
                error=parsed.error,
                edition_slug=parsed.edition_slug,
                track_number=parsed.track_number,
                track_key=parsed.track_key,
                group=parsed.group,
                role=parsed.role,
                register_role=parsed.register_role,
                title=parsed.title,
                stem_identity=parsed.stem_identity,
                stem_id=parsed.stem_id,
                import_key=parsed.import_key,
                file_url=file_url,
            )
        )

    duplicate_map: dict[str, list[str]] = {}
    for file in parsed_files:
        duplicate_map.setdefault(file.import_key, []).append(file.file_name)
    for import_key, names in duplicate_map.items():
        if len(names) > 1:
            errors.append(f"Mehrdeutige Dateien für {import_key}: {', '.join(names)}")

    edition_slugs = {_slug(edition.get("editionSlug")) for edition in editions if _slug(edition.get("editionSlug"))}
    known_groups: set[str] = set()
    known_roles: set[str] = set()
    for track in tracks:
        for stem in track.get("stems") or []:
            if not isinstance(stem, dict):
                continue
            if _slug(stem.get("group")):
                known_groups.add(_slug(stem.get("group")))
            if _slug(stem.get("role")):
                known_roles.add(_slug(stem.get("role")))

    tracks_by_key: dict[str, dict[str, Any]] = {}
    for track in tracks:
        track_number = _normalized_track_number(track.get("trackNumber"))
        edition_slug = _slug(track.get("editionSlug"))
        key = _text(track.get("trackKey")) or (f"{edition_slug}::{track_number}" if edition_slug and track_number else "")
        if key:
            tracks_by_key[key] = {**track, "stems": list(track.get("stems") or [])}

    working_tracks: dict[str, dict[str, Any]] = {}
    actions: list[dict[str, Any]] = []

    for parsed in sorted(parsed_files, key=lambda item: _natural_sort_key(item.import_key)):
        if len(duplicate_map.get(parsed.import_key, [])) > 1:
            continue

        if parsed.group not in known_groups:
            warnings.append(
                f'{parsed.file_name}: Gruppe "{parsed.group}" ist bisher in keinem Stem vorhanden – bitte Schreibweise prüfen.'
            )
            known_groups.add(parsed.group)
        if parsed.role not in known_roles:
            warnings.append(
                f'{parsed.file_name}: Rolle "{parsed.role}" ist bisher in keinem Stem vorhanden – bitte Schreibweise prüfen.'
            )
            known_roles.add(parsed.role)

        track = working_tracks.get(parsed.track_key) or tracks_by_key.get(parsed.track_key)
        is_new_track = False
        if track is None:
            if parsed.edition_slug not in edition_slugs:
                errors.append(f'{parsed.file_name}: Edition "{parsed.edition_slug}" existiert nicht in MH-Editions.')
                continue
            if not parsed.title:
                errors.append(
                    f'{parsed.file_name}: Track {parsed.track_key} existiert nicht. '
                    'Zum sicheren Anlegen fehlt nach " -- " ein Titel.'
                )
                continue
            track = _new_track_from_file(parsed)
            is_new_track = True
            warnings.append(f"{parsed.track_key} wird als unsichtbarer Entwurf angelegt.")
        else:
            track = {**track, "stems": list(track.get("stems") or [])}

        stems = track["stems"]
        existing_index = next(
            (index for index, stem in enumerate(stems) if _normalized_stem_identity(stem) == parsed.stem_identity),
            -1,
        )

        if existing_index >= 0:
            existing_stem = stems[existing_index]
            if _text(existing_stem.get("audioUrl")) == parsed.file_url:
                actions.append(
                    {
                        "type": "unchanged",
                        "trackKey": parsed.track_key,
                        "stemId": _text(existing_stem.get("id")) or parsed.stem_id,
                        "fileName": parsed.file_name,
                    }
                )
            else:
                stems[existing_index] = {**existing_stem, "audioUrl": parsed.file_url}
                actions.append(
                    {
                        "type": "replace-audio",
                        "trackKey": parsed.track_key,
                        "stemId": _text(existing_stem.get("id")) or parsed.stem_id,
                        "fileName": parsed.file_name,
                    }
                )
                warnings.append(f"{parsed.track_key}/{parsed.stem_id}: vorhandene Audiodatei wird ersetzt.")
        else:
            stems.append(_build_default_stem(parsed, parsed.file_url, stems))
            actions.append(
                {
                    "type": "create-track-and-stem" if is_new_track else "add-stem",
                    "trackKey": parsed.track_key,
                    "stemId": parsed.stem_id,
                    "fileName": parsed.file_name,
                }
            )

        working_tracks[parsed.track_key] = _finalize_track(track)

    writes: list[dict[str, Any]] = []
    for track in working_tracks.values():
        original = tracks_by_key.get(track.get("trackKey"))
        if original is None:
            writes.append(track)
            continue
        if json.dumps(_finalize_track(original), sort_keys=True) != json.dumps(track, sort_keys=True):
            writes.append(track)

    inserts = [track for track in writes if not track.get("_id")]
    updates = [track for track in writes if track.get("_id")]
    changed_actions = [action for action in actions if action["type"] != "unchanged"]

    if not parsed_files and not errors:
        warnings.append(
            "Keine MH-Tracks-Dateien erkannt. Erwartet: edition__track__gruppe__rolle[__register] -- Titel.mp3"
        )

    return MhTracksImportPlan(
        token=_plan_fingerprint(files, tracks),
        files=parsed_files,
        actions=actions,
        writes=writes,
        errors=errors,
        warnings=warnings,
        ignored_files=ignored_files,
        can_apply=not errors and bool(writes),
        summary={
            "recognizedFiles": len(parsed_files),
            "ignoredFiles": len(ignored_files),
            "unchangedFiles": len(actions) - len(changed_actions),
            "changedFiles": len(changed_actions),
            "inserts": len(inserts),
            "updates": len(updates),
            "errors": len(errors),
            "warnings": len(warnings),
        },
    )
