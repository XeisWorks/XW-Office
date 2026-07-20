"""Validated brand profiles used by every future content surface."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
import yaml


class ToneProfile(BaseModel):
    """Human-readable tone guidance for one brand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: str = Field(min_length=1)
    secondary: tuple[str, ...] = ()


class BrandProfile(BaseModel):
    """Stable, schema-validated content rules for one XeisWorks brand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(min_length=1)
    language: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    tone: ToneProfile
    forbidden_traits: tuple[str, ...] = ()
    preferred_terms: tuple[str, ...] = ()
    avoid_terms: tuple[str, ...] = ()
    emoji_maximum: int = Field(default=0, ge=0, le=20)
    hashtag_maximum: int = Field(default=0, ge=0, le=30)


class _BrandFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brands: tuple[BrandProfile, ...]


class BrandProfileCatalog:
    """Load brand profiles from the repository-owned YAML configuration."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> tuple[BrandProfile, ...]:
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"Brand profile configuration cannot be read: {self._path}") from exc

        parsed = _BrandFile.model_validate(raw)
        ids = [brand.id for brand in parsed.brands]
        if len(ids) != len(set(ids)):
            raise ValueError("Brand profile IDs must be unique")
        if not parsed.brands:
            raise ValueError("At least one brand profile is required")
        return parsed.brands
