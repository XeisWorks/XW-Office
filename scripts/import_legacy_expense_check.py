"""Import legacy Ausgaben-Check JSON into the shared pipeline.

The command is intentionally dry-run by default. It never changes the legacy
repository and writes only through XW-Office repositories when ``--apply`` is
explicitly supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from xw_office.core.config import load_config
from xw_office.core.database import create_session_factory
from xw_office.core.text_normalize import normalize_german_text
from xw_office.repositories.expense_pipeline import ExpensePipelineRepository


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else default


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    data_dir = args.source / "sevdesk_wix_fulfillment" / "ausgaben_check_data"
    cache_path = data_dir / "ausgaben_check_data" / "cache.json"
    if not cache_path.exists():
        cache_path = data_dir / "cache.json"
    links_path = data_dir / "missing_receipt_links.json"
    ignore_path = data_dir / "ausgaben_check_data" / "ignore.json"
    shift_path = data_dir / "ausgaben_check_data" / "shift.json"

    cache = _read(cache_path, {"flags": {}})
    links = _read(links_path, {"by_purpose": {}})
    ignores = _read(ignore_path, {})
    shifts = _read(shift_path, {})
    flags = cache.get("flags") if isinstance(cache.get("flags"), dict) else {}
    by_purpose = links.get("by_purpose") if isinstance(links.get("by_purpose"), dict) else {}

    flag_rows = [entry for rows in flags.values() if isinstance(rows, list) for entry in rows if isinstance(entry, dict)]
    link_rows = [(str(key), str(url)) for key, url in by_purpose.items() if str(url).startswith("https://")]
    source_hash = hashlib.sha256(
        b"".join(path.read_bytes() for path in (cache_path, links_path) if path.exists())
    ).hexdigest()
    print(json.dumps({
        "source_hash": source_hash,
        "flags": len(flag_rows),
        "supplier_links": len(link_rows),
        "ignore_entries": len(ignores) if isinstance(ignores, dict) else 0,
        "shift_entries": len(shifts) if isinstance(shifts, dict) else 0,
        "mode": "apply" if args.apply else "dry-run",
    }, ensure_ascii=False, indent=2))

    if not args.apply:
        return 0
    config = load_config()
    if not config.database_url.strip():
        raise SystemExit("DATABASE_URL ist für --apply erforderlich.")
    repo = ExpensePipelineRepository(create_session_factory(config))

    for entry in flag_rows:
        original = str(entry.get("original") or "").strip()
        normalized = str(entry.get("normalized") or "").strip()
        if normalized:
            repo.add_rule(
                profile_key="musikheroes",
                action="candidate",
                match_field="payee",
                value_normalized=normalize_german_text(normalized),
                value_original=original or normalized,
                source="legacy_import",
            )
    for purpose, url in link_rows:
        repo.add_supplier_link(
            profile_key="musikheroes",
            payee_normalized=normalize_german_text(purpose),
            counterparty_iban="",
            label=purpose,
            url=url,
            source="legacy_import",
        )
    print("Legacy-Daten importiert; erneutes Ausführen ist fachlich sichtbar und sollte vorab per Dry-Run geprüft werden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
