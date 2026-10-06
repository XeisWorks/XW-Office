"""Validated, atomic local snapshot; never an authority for printing."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from PySide6.QtCore import QIODevice, QSaveFile

from xw_office.print_center.models import PrintArticle

logger = logging.getLogger(__name__)


class CatalogueSnapshot(BaseModel):
    version: int = 1
    fingerprint: str
    resolved_at: float = Field(default_factory=time.time)
    articles: list[PrintArticle]


class CatalogueCache:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> CatalogueSnapshot | None:
        if not self._path.exists():
            return None
        try:
            snapshot = CatalogueSnapshot.model_validate_json(self._path.read_bytes())
        except (OSError, ValidationError) as exc:
            logger.warning("Druckcenter-Cache konnte nicht gelesen werden: %s", exc)
            return None
        if snapshot.version != 1 or any(a.source != "official" for a in snapshot.articles):
            logger.warning("Druckcenter-Cache ist inkompatibel; wird neu geladen.")
            return None
        return snapshot

    def write(self, snapshot: CatalogueSnapshot) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("Druckcenter-Cache-Verzeichnis nicht verfuegbar: %s", exc)
            return
        file = QSaveFile(str(self._path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            logger.warning("Druckcenter-Cache nicht beschreibbar: %s", file.errorString())
            return
        payload = snapshot.model_dump_json().encode("utf-8")
        if file.write(payload) != len(payload):
            logger.warning("Druckcenter-Cache unvollstaendig: %s", file.errorString())
            file.cancelWriting()
            return
        if not file.commit():
            logger.warning("Druckcenter-Cache konnte nicht gespeichert werden: %s", file.errorString())
