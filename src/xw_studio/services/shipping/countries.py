"""Country normalization for shipping labels and carrier integrations."""
from __future__ import annotations

import re
import unicodedata


_COUNTRY_BY_CODE = {
    "AT": "Austria",
    "AUT": "Austria",
    "BE": "Belgium",
    "BEL": "Belgium",
    "CH": "Switzerland",
    "CHE": "Switzerland",
    "CZ": "Czech Republic",
    "CZE": "Czech Republic",
    "DE": "Germany",
    "DEU": "Germany",
    "DK": "Denmark",
    "DNK": "Denmark",
    "EE": "Estonia",
    "EST": "Estonia",
    "FI": "Finland",
    "FIN": "Finland",
    "FR": "France",
    "FRA": "France",
    "HR": "Croatia",
    "HRV": "Croatia",
    "IT": "Italy",
    "ITA": "Italy",
    "LT": "Lithuania",
    "LTU": "Lithuania",
    "LU": "Luxembourg",
    "LUX": "Luxembourg",
    "LV": "Latvia",
    "LVA": "Latvia",
    "NL": "Netherlands",
    "NLD": "Netherlands",
    "NO": "Norway",
    "NOR": "Norway",
    "SE": "Sweden",
    "SWE": "Sweden",
    "SI": "Slovenia",
    "SVN": "Slovenia",
    "SK": "Slovakia",
    "SVK": "Slovakia",
}

_COUNTRY_BY_NAME = {
    "austria": "Austria",
    "belgien": "Belgium",
    "belgium": "Belgium",
    "croatia": "Croatia",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "daenemark": "Denmark",
    "danemark": "Denmark",
    "denmark": "Denmark",
    "deutschland": "Germany",
    "estland": "Estonia",
    "estonia": "Estonia",
    "finnland": "Finland",
    "finland": "Finland",
    "france": "France",
    "frankreich": "France",
    "germany": "Germany",
    "italien": "Italy",
    "italy": "Italy",
    "kroatien": "Croatia",
    "lettland": "Latvia",
    "latvia": "Latvia",
    "litauen": "Lithuania",
    "lithuania": "Lithuania",
    "luxembourg": "Luxembourg",
    "luxemburg": "Luxembourg",
    "netherlands": "Netherlands",
    "niederlande": "Netherlands",
    "norway": "Norway",
    "norwegen": "Norway",
    "oesterreich": "Austria",
    "osterreich": "Austria",
    "schweden": "Sweden",
    "schweiz": "Switzerland",
    "slovakia": "Slovakia",
    "slovak republic": "Slovakia",
    "slovakei": "Slovakia",
    "slovenia": "Slovenia",
    "slowenien": "Slovenia",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "tschechien": "Czech Republic",
}


def _extract_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in (
            "countryCode",
            "isoCountry",
            "addressCountry",
            "code",
            "alpha2",
            "alpha3",
            "countryFullname",
            "countryName",
            "country",
            "name",
            "displayName",
            "value",
            "label",
            "translated",
            "original",
        ):
            text = _extract_text(value.get(key))
            if text:
                return text
        return ""
    return str(value or "").strip()


def normalized_country_key(value: object) -> str:
    text = _extract_text(value).strip().casefold()
    if not text:
        return ""
    text = text.replace("ß", "ss").replace("ẞ", "ss")
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def country_name_en(value: object) -> str:
    """Return an English country name for labels, preserving unknown values."""
    text = _extract_text(value).strip()
    if not text:
        return ""
    mapped = _COUNTRY_BY_CODE.get(text.upper())
    if mapped:
        return mapped
    return _COUNTRY_BY_NAME.get(normalized_country_key(text), text)


def country_label_for_address(value: object) -> str:
    """Return the printable country label used on physical address labels."""
    return country_name_en(value).upper()
