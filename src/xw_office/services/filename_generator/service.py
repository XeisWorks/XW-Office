"""Builds MH-Tracks filenames for MH-AudioPlayer track uploads.

Stage 1 (this module): pure name generation, no filesystem access and no
renaming — the user copies the resulting names manually. See
``markdowns/`` conversation "Dateinamen-Generator" for the full rationale
and the planned Stage 2 (automated batch rename).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from uuid import uuid4

from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameGeneratorRequest,
    FilenameRenameBatchResult,
    FilenameRenameOperation,
    FilenameRenamePlanItem,
    FilenameRenameRules,
    validate_slug,
)

# Role tokens accepted by the MH-AudioPlayer/MH-Tracks importer (mhTracksImportCore.js ROLE_LABELS).
ROLE_LABELS: dict[str, str] = {
    "practice": "Üben",
    "performance": "Vorspiel",
    "teacher": "Duett/Lehrer",
    "voice": "Stimme",
    "mix": "Gesamt",
}

INSTRUMENT_SUGGESTIONS: tuple[str, ...] = ("trp", "pos", "ftb", "btb", "hrn")

LEGACY_PREFIX_RE = re.compile(r"^\s*(?P<track>\d{1,4})\.(?P<variant>\d+)(?:\s+|$)(?P<title>.*)$")
CANONICAL_NAME_RE = re.compile(
    r"^[a-z0-9][a-z0-9-]*__\d+__[a-z0-9][a-z0-9-]*__"
    r"[a-z0-9][a-z0-9-]*(?:__[a-z0-9][a-z0-9-]*)?(?: -- .+)?\.mp3$",
    re.IGNORECASE,
)


class FilenameGeneratorService:
    """Pure filename generation for the MH-Tracks naming convention."""

    def __init__(self) -> None:
        self._last_rename_batch: FilenameRenameBatchResult | None = None

    def build_filenames(self, request: FilenameGeneratorRequest) -> list[str]:
        if request.track_start < 1:
            raise FilenameGeneratorError("Der Track-Startwert muss mindestens 1 sein.")
        if request.track_end < request.track_start:
            raise FilenameGeneratorError("Der Track-Endwert darf nicht kleiner als der Startwert sein.")
        if not request.roles:
            raise FilenameGeneratorError("Bitte mindestens eine Rolle auswählen.")
        if request.track_width < 1:
            raise FilenameGeneratorError("Die Mindestbreite der Tracknummer muss mindestens 1 sein.")

        edition = validate_slug(request.edition_slug, field_name="Edition-Slug")
        instrument = validate_slug(request.instrument_slug, field_name="Instrument-Slug")
        roles = [validate_slug(role, field_name="Rolle") for role in request.roles]

        names: list[str] = []
        for track in range(request.track_start, request.track_end + 1):
            track_token = str(track).zfill(request.track_width)
            for role in roles:
                names.append(f"{edition}__{track_token}__{instrument}__{role}.mp3")
        return names

    @staticmethod
    def parse_mapping(value: str, *, field_name: str) -> dict[str, str]:
        """Parse ``source=target`` pairs separated by commas or semicolons."""
        result: dict[str, str] = {}
        for raw_pair in re.split(r"[,;\n]+", value):
            pair = raw_pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                raise FilenameGeneratorError(
                    f'{field_name}: "{pair}" muss als Quelle=Ziel angegeben werden.'
                )
            raw_source, raw_target = pair.split("=", 1)
            source = unicodedata.normalize("NFC", raw_source).strip().casefold()
            target = validate_slug(raw_target, field_name=field_name)
            if not source:
                raise FilenameGeneratorError(f"{field_name}: Die Quelle darf nicht leer sein.")
            if source in result and result[source] != target:
                raise FilenameGeneratorError(
                    f'{field_name}: "{source}" ist mehrfach unterschiedlich zugeordnet.'
                )
            result[source] = target
        return result

    def build_rename_plan(
        self,
        directory: Path | str,
        rules: FilenameRenameRules,
    ) -> list[FilenameRenamePlanItem]:
        """Scan one directory without modifying it and return a complete preview."""
        folder = Path(directory).expanduser().resolve()
        if not folder.is_dir():
            raise FilenameGeneratorError("Der ausgewählte Quellordner existiert nicht.")
        self._validate_rename_rules(rules)

        items = [
            self._plan_file(path, rules)
            for path in sorted(folder.iterdir(), key=lambda path: path.name.casefold())
            if path.is_file() and path.suffix.casefold() == ".mp3"
        ]
        return self._mark_plan_collisions(items)

    def execute_rename(
        self,
        directory: Path | str,
        operations: list[FilenameRenameOperation],
    ) -> FilenameRenameBatchResult:
        """Validate and transactionally rename selected files without overwriting."""
        folder = Path(directory).expanduser().resolve()
        normalized = self._validated_operations(folder, operations)
        self._transactional_rename(normalized)
        result = FilenameRenameBatchResult(folder, tuple(normalized))
        self._last_rename_batch = result
        return result

    def undo_last_rename(self) -> FilenameRenameBatchResult:
        """Undo the most recent batch from this application session."""
        batch = self._last_rename_batch
        if batch is None:
            raise FilenameGeneratorError("In dieser Sitzung gibt es keine Umbenennung zum Rückgängigmachen.")
        reverse = [
            FilenameRenameOperation(batch.directory / operation.target_name, operation.source_path.name)
            for operation in batch.operations
        ]
        normalized = self._validated_operations(batch.directory, reverse, require_canonical=False)
        self._transactional_rename(normalized)
        self._last_rename_batch = None
        return FilenameRenameBatchResult(batch.directory, tuple(normalized))

    @property
    def can_undo_last_rename(self) -> bool:
        return self._last_rename_batch is not None

    def _validate_rename_rules(self, rules: FilenameRenameRules) -> None:
        if rules.track_width < 1:
            raise FilenameGeneratorError("Die Mindestbreite der Tracknummer muss mindestens 1 sein.")
        for label, value in (
            ("Standard-Edition", rules.default_edition_slug),
            ("Standard-Instrument", rules.default_instrument_slug),
        ):
            if value.strip():
                validate_slug(value, field_name=label)
        if not rules.variant_roles:
            raise FilenameGeneratorError("Bitte mindestens eine Varianten-Zuordnung angeben.")
        for variant, role in rules.variant_roles.items():
            if not str(variant).isdigit():
                raise FilenameGeneratorError("Varianten müssen positive Zahlen sein.")
            validate_slug(role, field_name="Varianten-Rolle")
        for marker, slug in (*rules.edition_markers.items(), *rules.instrument_markers.items()):
            if not marker.strip():
                raise FilenameGeneratorError("Erkennungsmarker dürfen nicht leer sein.")
            validate_slug(slug, field_name="Marker-Ziel")

    def _plan_file(self, path: Path, rules: FilenameRenameRules) -> FilenameRenamePlanItem:
        normalized_stem = unicodedata.normalize("NFC", path.stem).strip()
        if CANONICAL_NAME_RE.fullmatch(path.name):
            return FilenameRenamePlanItem(
                source_path=path,
                target_name=path.name,
                status="canonical",
                message="Bereits im MH-Tracks-Format.",
            )

        match = LEGACY_PREFIX_RE.match(normalized_stem)
        if not match:
            return FilenameRenamePlanItem(
                source_path=path,
                target_name="",
                status="review",
                message="Kein Präfix wie 03.2 erkannt.",
            )

        raw_track = match.group("track")
        variant = match.group("variant")
        raw_title = match.group("title").strip()
        role = rules.variant_roles.get(variant, "")
        edition, edition_error, edition_markers = self._resolve_value(
            normalized_stem,
            rules.default_edition_slug,
            rules.edition_markers,
            rules.markers_override_defaults,
            "Edition",
        )
        instrument, instrument_error, instrument_markers = self._resolve_value(
            normalized_stem,
            rules.default_instrument_slug,
            rules.instrument_markers,
            rules.markers_override_defaults,
            "Instrument",
        )
        title = self._clean_title(raw_title, (*edition_markers, *instrument_markers))
        track = str(int(raw_track)).zfill(rules.track_width)
        errors = [message for message in (edition_error, instrument_error) if message]
        if not role:
            errors.append(f"Variante .{variant} ist nicht zugeordnet.")
        if not edition:
            errors.append("Edition konnte nicht bestimmt werden.")
        if not instrument:
            errors.append("Instrument konnte nicht bestimmt werden.")

        target = ""
        if not errors:
            target = f"{edition}__{track}__{instrument}__{role}"
            if rules.keep_title and title:
                target += f" -- {title}"
            target += ".mp3"
        return FilenameRenamePlanItem(
            source_path=path,
            target_name=target,
            track_number=track,
            variant=variant,
            edition_slug=edition,
            instrument_slug=instrument,
            role=role,
            title=title,
            status="ready" if not errors else "review",
            message="Eindeutig erkannt." if not errors else " ".join(errors),
        )

    @staticmethod
    def _marker_tokens(value: str) -> tuple[str, ...]:
        normalized = unicodedata.normalize("NFC", value).casefold()
        return tuple(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))

    def _matching_markers(self, text: str, mapping: dict[str, str]) -> list[tuple[str, str]]:
        haystack = self._marker_tokens(text)
        matches: list[tuple[str, str]] = []
        for marker, target in mapping.items():
            needle = self._marker_tokens(marker)
            if needle and any(haystack[index : index + len(needle)] == needle for index in range(len(haystack))):
                matches.append((marker, target.strip().lower()))
        return matches

    def _resolve_value(
        self,
        text: str,
        default: str,
        mapping: dict[str, str],
        markers_override_defaults: bool,
        label: str,
    ) -> tuple[str, str, tuple[str, ...]]:
        matches = self._matching_markers(text, mapping)
        matched_values = {target for _, target in matches}
        matched_markers = tuple(marker for marker, _ in matches)
        if len(matched_values) > 1:
            return "", f"Mehrere {label}-Marker erkannt: {', '.join(matched_markers)}.", matched_markers
        detected = next(iter(matched_values), "")
        fallback = default.strip().lower()
        if detected and fallback and detected != fallback and not markers_override_defaults:
            return "", f'{label}-Marker ergibt "{detected}", Preset erwartet "{fallback}".', matched_markers
        return (detected if markers_override_defaults and detected else fallback or detected), "", matched_markers

    def _clean_title(self, title: str, markers: tuple[str, ...]) -> str:
        cleaned = unicodedata.normalize("NFC", title)
        for marker in sorted(set(markers), key=len, reverse=True):
            marker_pattern = r"[\s_-]+".join(re.escape(part) for part in self._marker_tokens(marker))
            cleaned = re.sub(rf"(?<!\w){marker_pattern}(?!\w)", " ", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", cleaned).strip(" -_")

    def _mark_plan_collisions(
        self, items: list[FilenameRenamePlanItem]
    ) -> list[FilenameRenamePlanItem]:
        target_counts: dict[str, int] = {}
        movable_source_names = {
            item.source_path.name.casefold() for item in items if item.status == "ready"
        }
        for item in items:
            if item.target_name and item.status == "ready":
                key = item.target_name.casefold()
                target_counts[key] = target_counts.get(key, 0) + 1

        result: list[FilenameRenamePlanItem] = []
        for item in items:
            message = ""
            if item.status == "ready" and target_counts.get(item.target_name.casefold(), 0) > 1:
                message = "Mehrere Quelldateien würden denselben Zielnamen erhalten."
            target_path = item.source_path.with_name(item.target_name) if item.target_name else None
            if (
                not message
                and item.status == "ready"
                and target_path is not None
                and target_path.exists()
                and target_path.name.casefold() not in movable_source_names
            ):
                message = "Der Zielname existiert bereits."
            if message:
                result.append(
                    FilenameRenamePlanItem(
                        **{**item.__dict__, "status": "conflict", "message": message}
                    )
                )
            else:
                result.append(item)
        return result

    def _validated_operations(
        self,
        folder: Path,
        operations: list[FilenameRenameOperation],
        *,
        require_canonical: bool = True,
    ) -> list[FilenameRenameOperation]:
        if not folder.is_dir():
            raise FilenameGeneratorError("Der Quellordner existiert nicht mehr.")
        if not operations:
            raise FilenameGeneratorError("Bitte mindestens eine Datei auswählen.")
        normalized: list[FilenameRenameOperation] = []
        seen_sources: set[str] = set()
        seen_targets: set[str] = set()
        for operation in operations:
            source = operation.source_path.resolve()
            try:
                source.relative_to(folder)
            except ValueError as exc:
                raise FilenameGeneratorError("Eine Quelldatei liegt außerhalb des gewählten Ordners.") from exc
            if source.parent != folder or not source.is_file():
                raise FilenameGeneratorError(f'Quelldatei fehlt: "{source.name}".')
            target_name = operation.target_name.strip()
            invalid_shape = Path(target_name).name != target_name or not target_name
            invalid_contract = require_canonical and not CANONICAL_NAME_RE.fullmatch(target_name)
            if invalid_shape or invalid_contract:
                raise FilenameGeneratorError(
                    f'Ungültiger Zielname: "{target_name}".'
                    + (" Erwartet wird das MH-Tracks-Format." if require_canonical else "")
                )
            source_key = source.name.casefold()
            target_key = target_name.casefold()
            if source_key in seen_sources:
                raise FilenameGeneratorError(f'Datei doppelt ausgewählt: "{source.name}".')
            if target_key in seen_targets:
                raise FilenameGeneratorError(f'Zielname doppelt vergeben: "{target_name}".')
            seen_sources.add(source_key)
            seen_targets.add(target_key)
            normalized.append(FilenameRenameOperation(source, target_name))

        for operation in normalized:
            target = folder / operation.target_name
            if target.exists() and target.name.casefold() not in seen_sources:
                raise FilenameGeneratorError(f'Zieldatei existiert bereits: "{target.name}".')
        return normalized

    @staticmethod
    def _transactional_rename(operations: list[FilenameRenameOperation]) -> None:
        staged: list[tuple[Path, Path, Path]] = []
        try:
            for operation in operations:
                source = operation.source_path
                temp = source.with_name(f".xw-rename-{uuid4().hex}{source.suffix}")
                source.rename(temp)
                staged.append((source, temp, source.with_name(operation.target_name)))
            completed: list[tuple[Path, Path, Path]] = []
            for source, temp, target in staged:
                temp.rename(target)
                completed.append((source, temp, target))
        except OSError as exc:
            for source, _temp, target in reversed(locals().get("completed", [])):
                if target.exists() and not source.exists():
                    target.rename(source)
            for source, temp, _target in reversed(staged):
                if temp.exists() and not source.exists():
                    temp.rename(source)
            raise FilenameGeneratorError(f"Umbenennung fehlgeschlagen und wurde zurückgerollt: {exc}") from exc
