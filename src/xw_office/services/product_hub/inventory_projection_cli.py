"""One-shot canonical inventory projection to sevDesk and Wix."""
from __future__ import annotations

import argparse
import json
import os

from xw_office.core.config import load_config
from xw_office.core.database import create_session_factory
from xw_office.services.http_client import build_sevdesk_connection
from xw_office.services.product_hub.inventory_projection import InventoryProjectionService
from xw_office.services.sevdesk.part_client import PartClient
from xw_office.services.wix.product_details_client import WixProductDetailsClient


class _EnvironmentSecrets:
    """Minimal secret source for the non-web Railway worker process."""

    def get_secret(self, name: str) -> str:
        return str(os.getenv(name) or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply provider writes; without this flag the command is read-only.",
    )
    args = parser.parse_args(argv)
    config = load_config()
    if not (config.database_url or "").strip():
        parser.error("DATABASE_URL is required")
    if args.write and not config.product_hub.inventory_master_enabled:
        parser.error("inventory_master_enabled must be enabled before provider writes")
    if args.write and not (config.sevdesk.api_token or "").strip():
        parser.error("SEVDESK_API_TOKEN is required for provider writes")

    wix = WixProductDetailsClient(secret_service=_EnvironmentSecrets())  # type: ignore[arg-type]
    result = InventoryProjectionService(
        create_session_factory(config),
        sevdesk=PartClient(build_sevdesk_connection(config)),
        wix=wix,
        write_enabled=lambda: bool(config.product_hub.inventory_master_enabled),
    ).run(dry_run=not args.write)
    payload = {
        "dry_run": not args.write,
        "projected": result.projected,
        "would_project": result.would_project,
        "equal": result.equal,
        "conflicts": result.conflicts,
        "skipped": result.skipped,
        "errors": result.errors,
        "items": [item.__dict__ for item in result.items],
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 1 if result.errors or result.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())

