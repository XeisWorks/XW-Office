"""Append-only JSON idea list for Marketing / Notensatz modules."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_studio.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)


@dataclass
class IdeaEntry:
    title: str
    body: str
    lane: str = "backlog"
    channel: str = ""
    due_date: str = ""


class IdeasStore:
    """Thread-safe DB-backed store with local JSON migration/fallback."""

    def __init__(
        self,
        path: Path,
        settings_repo: "SettingKvRepository | None" = None,
        settings_key: str = "",
    ) -> None:
        self._path = path
        self._settings_repo = settings_repo
        self._settings_key = str(settings_key or "").strip()
        self._lock = Lock()
        self._migrate_local_file_if_needed()

    @staticmethod
    def _decode(raw: str | None) -> list[IdeaEntry]:
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        out: list[IdeaEntry] = []
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    out.append(
                        IdeaEntry(
                            title=str(item.get("title", "")),
                            body=str(item.get("body", "")),
                            lane=str(item.get("lane", "backlog") or "backlog"),
                            channel=str(item.get("channel", "") or ""),
                            due_date=str(item.get("due_date", "") or ""),
                        )
                    )
        return out

    @staticmethod
    def _encode(entries: list[IdeaEntry]) -> str:
        return json.dumps([asdict(entry) for entry in entries], ensure_ascii=False, indent=2)

    def _read_local_raw(self) -> str | None:
        if not self._path.exists():
            return None
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Ideas file unreadable %s: %s", self._path, exc)
            return None

    def _migrate_local_file_if_needed(self) -> None:
        if self._settings_repo is None or not self._settings_key:
            return
        if self._settings_repo.get_value_json(self._settings_key) is not None:
            return
        local_raw = self._read_local_raw()
        if local_raw is None:
            return
        entries = self._decode(local_raw)
        encoded = self._encode(entries)
        self._settings_repo.mutate_value_json(
            self._settings_key,
            lambda current: current if current is not None else encoded,
        )
        logger.info("Migrated %d ideas from %s to Railway key %s", len(entries), self._path, self._settings_key)

    def _read_all(self) -> list[IdeaEntry]:
        if self._settings_repo is not None and self._settings_key:
            return self._decode(self._settings_repo.get_value_json(self._settings_key))
        return self._decode(self._read_local_raw())

    def list_ideas(self) -> list[IdeaEntry]:
        with self._lock:
            return self._read_all()

    def add_idea(self, entry: IdeaEntry) -> None:
        with self._lock:
            if self._settings_repo is not None and self._settings_key:
                self._settings_repo.mutate_value_json(
                    self._settings_key,
                    lambda raw: self._encode([*self._decode(raw), entry]),
                )
                return
            rows = self._read_all()
            rows.append(entry)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(self._encode(rows), encoding="utf-8")

    def replace_all(self, entries: list[IdeaEntry]) -> None:
        """Overwrite the full list (e.g. after a delete)."""
        with self._lock:
            if self._settings_repo is not None and self._settings_key:
                self._settings_repo.set_value_json(self._settings_key, self._encode(entries))
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(self._encode(entries), encoding="utf-8")
