"""Least-privilege settings writer for the standalone print center."""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text

from xw_office.models.settings_kv import SettingKV
from xw_office.repositories.settings_kv import SettingKvRepository


class PrintCenterSettingsRepository(SettingKvRepository):
    """Route the one permitted PostgreSQL write through a guarded DB function."""

    def mutate_value_json(
        self,
        key: str,
        mutator: Callable[[str | None], str],
    ) -> str:
        if key != "inventory.products":
            raise PermissionError(f"Das Druckcenter darf die Einstellung {key!r} nicht aendern.")
        with self._scope() as session:
            bind = session.get_bind()
            if bind is None or bind.dialect.name != "postgresql":
                row = session.get(SettingKV, key)
                updated = mutator(None if row is None else row.value_json)
                if row is None:
                    session.add(SettingKV(key=key, value_json=updated))
                else:
                    row.value_json = updated
                session.flush()
                return updated
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )
            row = session.get(SettingKV, key)
            updated = mutator(None if row is None else row.value_json)
            session.execute(
                text("SELECT public.xw_print_center_set_inventory_products(:payload)"),
                {"payload": updated},
            )
            return updated
