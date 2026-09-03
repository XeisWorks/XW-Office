"""Data contracts for the MH-AudioPlayer filename generator (Layout module).

Target naming convention (see MH-AudioPlayer / XW-Website_v2
``mhTracksImportCore.js``): ``{edition}__{track}__{instrument}__{role}.mp3``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class FilenameGeneratorError(Exception):
    """Invalid slug, track range, or role list."""


def validate_slug(value: str, *, field_name: str) -> str:
    """Lowercase and validate a slug (letters/digits/hyphen, e.g. 'sk-t', 'btb')."""
    slug = value.strip().lower()
    if not _SLUG_RE.match(slug):
        raise FilenameGeneratorError(
            f"{field_name} muss aus Kleinbuchstaben, Ziffern und Bindestrichen bestehen (z. B. 'sk-t')."
        )
    return slug


@dataclass(frozen=True)
class FilenameGeneratorRequest:
    """User input for one batch of MH-Tracks filenames."""

    edition_slug: str
    instrument_slug: str
    track_start: int
    track_end: int
    roles: tuple[str, ...]
    track_width: int = 2
