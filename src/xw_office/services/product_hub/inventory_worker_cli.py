"""Long-running inventory worker suitable for a dedicated Railway service."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from xw_office.services.product_hub.forecast_cli import main as forecast_main
from xw_office.services.product_hub.inventory_sync_cli import main as sync_main

logger = logging.getLogger("xw.inventory-worker")


def _configure_logging() -> None:
    """Make worker lifecycle messages visible in Railway/container logs."""
    level_name = str(os.getenv("XW_INVENTORY_WORKER_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    for noisy_logger in ("httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def run_once(*, forecast_years: int = 5, credit_years: int = 1) -> tuple[int, int]:
    """Run both idempotent jobs once and return their exit codes."""
    forecast_exit = forecast_main(["--years", str(forecast_years)])
    sync_exit = sync_main(["--years", str(credit_years)])
    return forecast_exit, sync_exit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run recurring Product-Hub inventory jobs")
    parser.add_argument("--interval-seconds", type=int, default=86400)
    parser.add_argument("--forecast-years", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--credit-years", type=int, default=1, choices=range(1, 6))
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args(argv)
    interval = max(60, int(args.interval_seconds))
    _configure_logging()
    logger.info(
        "Inventory worker started interval_seconds=%s forecast_years=%s credit_years=%s once=%s",
        interval,
        args.forecast_years,
        args.credit_years,
        args.once,
    )
    while True:
        try:
            forecast_exit, sync_exit = run_once(
                forecast_years=int(args.forecast_years), credit_years=int(args.credit_years)
            )
            logger.info("Inventory cycle finished forecast=%s sync=%s", forecast_exit, sync_exit)
            if forecast_exit or sync_exit:
                logger.error("Inventory cycle reported issues: forecast=%s sync=%s", forecast_exit, sync_exit)
                if args.once:
                    return 1
        except Exception:  # noqa: BLE001 - worker must survive transient sevDesk/network errors
            logger.exception("Inventory cycle failed; retrying on next interval")
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())

