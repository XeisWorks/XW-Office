from __future__ import annotations

from decimal import Decimal

from xw_office.services.plc.pricing import quote_plc_price


def test_austria_price_uses_next_matching_weight_bracket() -> None:
    quote = quote_plc_price(product_id="10", country_iso2="AT", weight_kg="2,01")

    assert quote is not None
    assert quote.price_eur == Decimal("6.39")
    assert quote.max_weight_kg == Decimal("4")


def test_germany_uses_dedicated_premium_tariff_instead_of_zone_one() -> None:
    quote = quote_plc_price(product_id="45", country_iso2="DE", weight_kg="8")

    assert quote is not None
    assert quote.price_eur == Decimal("12.88")
    assert quote.tariff_name == "Deutschland"


def test_english_country_iso_code_maps_to_zone() -> None:
    quote = quote_plc_price(product_id="45", country_iso2="FR", weight_kg="4")

    assert quote is not None
    assert quote.price_eur == Decimal("16.89")
    assert quote.tariff_name == "Zone 3"


def test_plus_for_european_non_premium_country_uses_zone_two() -> None:
    quote = quote_plc_price(product_id="70", country_iso2="CH", weight_kg="12.01")

    assert quote is not None
    assert quote.price_eur == Decimal("59.53")
    assert quote.max_weight_kg == Decimal("31.5")


def test_missing_tariff_or_excess_weight_returns_no_price() -> None:
    assert quote_plc_price(product_id="70", country_iso2="IT", weight_kg="2") is None
    assert quote_plc_price(product_id="70", country_iso2="FR", weight_kg="2") is None
    assert quote_plc_price(product_id="45", country_iso2="DE", weight_kg="31.51") is None
    assert quote_plc_price(product_id="45", country_iso2="DE", weight_kg="invalid") is None
