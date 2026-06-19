from __future__ import annotations

from pathlib import Path

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


def test_wix_order_cache_short_caches_missing_orders(tmp_path: Path) -> None:
    cache = WixOrderCache(tmp_path / "cache.sqlite")

    cache.put_missing(site_id="site", account_id="", reference="missing")

    hit = cache.get_order(site_id="site", account_id="", reference="missing")

    assert hit is not None
    assert hit.found is False
    assert hit.order == {}
