from __future__ import annotations

from pathlib import Path
import sqlite3

from xw_studio.services.wix.order_cache import WixOrderCache


def test_wix_order_cache_persists_order_aliases(tmp_path: Path) -> None:
    cache = WixOrderCache(tmp_path / "cache.sqlite")
    order = {
        "id": "order-id-1",
        "number": "20845",
        "orderNumber": "20845",
        "buyerInfo": {"email": "kunde@example.test"},
    }

    cache.put_order(site_id="site", account_id="", reference="20845", order=order)

    by_number = cache.get_order(site_id="site", account_id="", reference="20845")
    by_id = cache.get_order(site_id="site", account_id="", reference="order-id-1")

    assert by_number is not None
    assert by_number.found is True
    assert by_number.order["id"] == "order-id-1"
    assert by_id is not None
    assert by_id.order["number"] == "20845"


def test_wix_order_cache_keeps_successful_orders_until_explicitly_pruned(tmp_path: Path) -> None:
    cache = WixOrderCache(tmp_path / "cache.sqlite")
    cache.put_order(
        site_id="site",
        account_id="",
        reference="20845",
        order={"id": "order-id-1", "number": "20845"},
    )
    with sqlite3.connect(cache.path) as con:
        con.execute("UPDATE wix_order_cache SET fetched_at = 0")

    permanent_hit = cache.get_order(site_id="site", account_id="", reference="20845")
    explicitly_expired = cache.get_order(
        site_id="site",
        account_id="",
        reference="20845",
        max_age_seconds=1,
    )

    assert permanent_hit is not None
    assert permanent_hit.found is True
    assert explicitly_expired is None


def test_wix_order_cache_keeps_missing_orders_until_explicitly_expired(tmp_path: Path) -> None:
    cache = WixOrderCache(tmp_path / "cache.sqlite")

    cache.put_missing(site_id="site", account_id="", reference="missing")
    with sqlite3.connect(cache.path) as con:
        con.execute("UPDATE wix_order_cache SET fetched_at = 0")

    hit = cache.get_order(site_id="site", account_id="", reference="missing")
    explicitly_expired = cache.get_order(
        site_id="site",
        account_id="",
        reference="missing",
        missing_ttl_seconds=1,
    )

    assert hit is not None
    assert hit.found is False
    assert hit.order == {}
    assert explicitly_expired is None
