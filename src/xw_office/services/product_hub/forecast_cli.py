"""One-shot production forecast refresh for Railway cron jobs."""
from __future__ import annotations

import argparse
import datetime as dt
import json

from xw_office.core.config import load_config
from xw_office.core.database import create_session_factory
from xw_office.services.http_client import build_sevdesk_connection
from xw_office.services.product_hub.inventory_forecast_refresh import InventoryForecastRefreshService
from xw_office.services.product_hub.sevdesk_history_audit import sevdesk_history_provider_from_connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh Product-Hub reorder points from sevDesk history")
    parser.add_argument("--years", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--as-of", dest="as_of", help="ISO date; defaults to today")
    args = parser.parse_args(argv)
    config = load_config()
    if not (config.database_url or "").strip():
        parser.error("DATABASE_URL is required")
    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    service = InventoryForecastRefreshService(
        create_session_factory(config),
        sevdesk_history_provider_from_connection(build_sevdesk_connection(config)),
    )
    result = service.refresh(as_of=as_of, years=int(args.years))
    print(json.dumps({"refreshed": result.refreshed, "skipped": result.skipped, "errors": result.errors}, ensure_ascii=False))
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

