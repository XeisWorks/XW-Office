"""Deterministic PLC price lookup for the tariffs shown in the label dialog."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class PlcPriceQuote:
    price_eur: Decimal
    max_weight_kg: Decimal
    tariff_name: str


_PREMIUM_PRODUCT_ID = "45"
_PLUS_PRODUCT_ID = "70"
_AUSTRIA_PRODUCT_ID = "10"

_PREMIUM_ZONE_BY_COUNTRY = {
    "HR": "Zone 1",
    "PL": "Zone 1",
    "SK": "Zone 1",
    "SI": "Zone 1",
    "CZ": "Zone 1",
    "HU": "Zone 1",
    "BE": "Zone 2",
    "DK": "Zone 2",
    "IT": "Zone 2",
    "NL": "Zone 2",
    "FI": "Zone 3",
    "FR": "Zone 3",
    "LU": "Zone 3",
    "RO": "Zone 3",
    "SE": "Zone 3",
    "BG": "Zone 4",
    "EE": "Zone 4",
    "LV": "Zone 4",
    "LT": "Zone 4",
    "PT": "Zone 4",
    "ES": "Zone 4",
    "GR": "Zone 5",
    "GB": "Zone 5",
    "IE": "Zone 5",
    "IS": "Zone 5",
    "MT": "Zone 5",
    "NO": "Zone 5",
    "CY": "Zone 5",
}

_PLUS_ZONE_2_COUNTRIES = frozenset(
    {
        "AD",
        "AL",
        "AM",
        "AZ",
        "BA",
        "BY",
        "CH",
        "FO",
        "GB",
        "GE",
        "GI",
        "GL",
        "IS",
        "LI",
        "MD",
        "ME",
        "MK",
        "NO",
        "RS",
        "RU",
        "SM",
        "TR",
        "UA",
        "VA",
        "XK",
    }
)

_TARIFFS: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    (_PREMIUM_PRODUCT_ID, "Deutschland"): (
        ("2", "8.96"),
        ("4", "10.20"),
        ("8", "12.88"),
        ("12", "15.97"),
        ("20", "16.69"),
        ("31.5", "19.16"),
    ),
    (_PREMIUM_PRODUCT_ID, "Zone 1"): (
        ("2", "10.20"),
        ("4", "11.33"),
        ("8", "14.32"),
        ("12", "17.51"),
        ("20", "19.78"),
        ("31.5", "21.63"),
    ),
    (_PREMIUM_PRODUCT_ID, "Zone 2"): (
        ("2", "12.57"),
        ("4", "14.21"),
        ("8", "15.66"),
        ("12", "17.10"),
        ("20", "19.16"),
        ("31.5", "22.66"),
    ),
    (_PREMIUM_PRODUCT_ID, "Zone 3"): (
        ("2", "15.35"),
        ("4", "16.89"),
        ("8", "18.75"),
        ("12", "19.98"),
        ("20", "21.32"),
        ("31.5", "24.31"),
    ),
    (_PREMIUM_PRODUCT_ID, "Zone 4"): (
        ("2", "16.27"),
        ("4", "18.03"),
        ("8", "21.32"),
        ("12", "26.47"),
        ("20", "35.95"),
        ("31.5", "47.17"),
    ),
    (_PREMIUM_PRODUCT_ID, "Zone 5"): (
        ("2", "20.29"),
        ("4", "24.21"),
        ("8", "32.34"),
        ("12", "45.11"),
        ("20", "61.39"),
        ("31.5", "74.88"),
    ),
    (_PLUS_PRODUCT_ID, "Zone 2"): (
        ("2", "17.20"),
        ("4", "19.88"),
        ("8", "26.37"),
        ("12", "35.23"),
        ("31.5", "59.53"),
    ),
    (_AUSTRIA_PRODUCT_ID, "Österreich"): (
        ("2", "5.46"),
        ("4", "6.39"),
        ("8", "7.21"),
        ("12", "8.55"),
        ("20", "9.79"),
        ("31.5", "10.92"),
    ),
}


def quote_plc_price(
    *,
    product_id: object,
    country_iso2: object,
    weight_kg: object,
) -> PlcPriceQuote | None:
    """Return the first tariff bracket that contains the shipment weight."""
    product = str(product_id or "").strip()
    country = str(country_iso2 or "").strip().upper()
    try:
        weight = Decimal(str(weight_kg or "").strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if weight <= 0:
        return None

    if product == _AUSTRIA_PRODUCT_ID and country == "AT":
        tariff_name = "Österreich"
    elif product == _PREMIUM_PRODUCT_ID and country == "DE":
        tariff_name = "Deutschland"
    elif product == _PREMIUM_PRODUCT_ID:
        tariff_name = _PREMIUM_ZONE_BY_COUNTRY.get(country, "")
    elif product == _PLUS_PRODUCT_ID and country in _PLUS_ZONE_2_COUNTRIES:
        tariff_name = "Zone 2"
    else:
        tariff_name = ""
    brackets = _TARIFFS.get((product, tariff_name), ())
    for max_weight_raw, price_raw in brackets:
        max_weight = Decimal(max_weight_raw)
        if weight <= max_weight:
            return PlcPriceQuote(
                price_eur=Decimal(price_raw),
                max_weight_kg=max_weight,
                tariff_name=tariff_name,
            )
    return None
