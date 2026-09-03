"""Builds MH-Tracks filenames for MH-AudioPlayer track uploads.

Stage 1 (this module): pure name generation, no filesystem access and no
renaming — the user copies the resulting names manually. See
``markdowns/`` conversation "Dateinamen-Generator" for the full rationale
and the planned Stage 2 (automated batch rename).
"""
from __future__ import annotations

from xw_office.services.filename_generator.models import (
    FilenameGeneratorError,
    FilenameGeneratorRequest,
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


class FilenameGeneratorService:
    """Pure filename generation for the MH-Tracks naming convention."""

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
