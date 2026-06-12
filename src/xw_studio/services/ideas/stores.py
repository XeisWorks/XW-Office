"""Typed :class:`IdeasStore` singletons for DI."""
from __future__ import annotations

from pathlib import Path

from xw_studio.services.ideas.store import IdeasStore

MARKETING_IDEAS_KEY = "ideas.marketing"
NOTATION_IDEAS_KEY = "ideas.notation"


class MarketingIdeasStore(IdeasStore):
    """Marketing / content ideas."""


class NotationIdeasStore(IdeasStore):
    """Notation / Musikprojekt-Ideen."""


def default_marketing_ideas_path() -> Path:
    return Path("data") / "marketing_ideas.json"


def default_notation_ideas_path() -> Path:
    return Path("data") / "notation_ideas.json"
