"""Data contracts for the MH-AudioPlayer filename generator (Layout module).

Target naming convention (see MH-AudioPlayer / XW-Website_v2
``mhTracksImportCore.js``): ``{edition}__{track}__{instrument}__{role}.mp3``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass(frozen=True)
class FilenameRenameRules:
    """Configurable rules for turning legacy audio names into MH-Tracks names."""

    default_edition_slug: str = ""
    default_instrument_slug: str = ""
    variant_roles: dict[str, str] = field(
        default_factory=lambda: {"1": "practice", "2": "teacher"}
    )
    edition_markers: dict[str, str] = field(
        default_factory=lambda: {"tief": "sk-t", "hoch": "sk-h"}
    )
    instrument_markers: dict[str, str] = field(
        default_factory=lambda: {
            "btb": "btb",
            "b-tuba": "btb",
            "ftb": "ftb",
            "posaune": "pos",
            "pos": "pos",
            "trompete": "trp",
            "trp": "trp",
            "horn": "hrn",
            "hrn": "hrn",
        }
    )
    markers_override_defaults: bool = False
    keep_title: bool = False
    track_width: int = 2


@dataclass(frozen=True)
class FilenameRenamePlanItem:
    """One source file and its deterministic rename assessment."""

    source_path: Path
    target_name: str
    track_number: str = ""
    variant: str = ""
    edition_slug: str = ""
    instrument_slug: str = ""
    role: str = ""
    title: str = ""
    status: str = "review"
    message: str = ""

    @property
    def is_safe(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class FilenameRenameOperation:
    """A user-approved source/target pair within one directory."""

    source_path: Path
    target_name: str


@dataclass(frozen=True)
class FilenameRenameBatchResult:
    """Completed batch, retained in memory so it can be undone safely."""

    directory: Path
    operations: tuple[FilenameRenameOperation, ...]
