"""Country normalization for shipping labels and carrier integrations."""
from __future__ import annotations

import re
import unicodedata


_COUNTRY_BY_CODE = {
    "AD": "Andorra",
    "AND": "Andorra",
    "AL": "Albania",
    "ALB": "Albania",
    "AM": "Armenia",
    "ARM": "Armenia",
    "AT": "Austria",
    "AUT": "Austria",
    "AX": "Aland Islands",
    "ALA": "Aland Islands",
    "AZ": "Azerbaijan",
    "AZE": "Azerbaijan",
    "BA": "Bosnia and Herzegovina",
    "BIH": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BEL": "Belgium",
    "BG": "Bulgaria",
    "BGR": "Bulgaria",
    "BY": "Belarus",
    "BLR": "Belarus",
    "CH": "Switzerland",
    "CHE": "Switzerland",
    "CY": "Cyprus",
    "CYP": "Cyprus",
    "CZ": "Czech Republic",
    "CZE": "Czech Republic",
    "DE": "Germany",
    "DEU": "Germany",
    "DK": "Denmark",
    "DNK": "Denmark",
    "EE": "Estonia",
    "EST": "Estonia",
    "ES": "Spain",
    "ESP": "Spain",
    "FI": "Finland",
    "FIN": "Finland",
    "FO": "Faroe Islands",
    "FRO": "Faroe Islands",
    "FR": "France",
    "FRA": "France",
    "GB": "United Kingdom",
    "GBR": "United Kingdom",
    "GE": "Georgia",
    "GEO": "Georgia",
    "GI": "Gibraltar",
    "GIB": "Gibraltar",
    "GG": "Guernsey",
    "GGY": "Guernsey",
    "GR": "Greece",
    "GRC": "Greece",
    "HR": "Croatia",
    "HRV": "Croatia",
    "HU": "Hungary",
    "HUN": "Hungary",
    "IE": "Ireland",
    "IRL": "Ireland",
    "IM": "Isle of Man",
    "IMN": "Isle of Man",
    "IS": "Iceland",
    "ISL": "Iceland",
    "IT": "Italy",
    "ITA": "Italy",
    "JE": "Jersey",
    "JEY": "Jersey",
    "KZ": "Kazakhstan",
    "KAZ": "Kazakhstan",
    "LT": "Lithuania",
    "LTU": "Lithuania",
    "LI": "Liechtenstein",
    "LIE": "Liechtenstein",
    "LU": "Luxembourg",
    "LUX": "Luxembourg",
    "LV": "Latvia",
    "LVA": "Latvia",
    "MC": "Monaco",
    "MCO": "Monaco",
    "MD": "Moldova",
    "MDA": "Moldova",
    "ME": "Montenegro",
    "MNE": "Montenegro",
    "MK": "North Macedonia",
    "MKD": "North Macedonia",
    "MT": "Malta",
    "MLT": "Malta",
    "NL": "Netherlands",
    "NLD": "Netherlands",
    "NO": "Norway",
    "NOR": "Norway",
    "PL": "Poland",
    "POL": "Poland",
    "PT": "Portugal",
    "PRT": "Portugal",
    "RO": "Romania",
    "ROU": "Romania",
    "RS": "Serbia",
    "SRB": "Serbia",
    "RU": "Russia",
    "RUS": "Russia",
    "SE": "Sweden",
    "SWE": "Sweden",
    "SI": "Slovenia",
    "SVN": "Slovenia",
    "SK": "Slovakia",
    "SVK": "Slovakia",
    "SM": "San Marino",
    "SMR": "San Marino",
    "TR": "Turkey",
    "TUR": "Turkey",
    "UA": "Ukraine",
    "UKR": "Ukraine",
    "VA": "Vatican City",
    "VAT": "Vatican City",
    "XK": "Kosovo",
    "XKX": "Kosovo",
}

_COUNTRY_BY_NAME = {
    "aland islands": "Aland Islands",
    "alandinseln": "Aland Islands",
    "albania": "Albania",
    "albanien": "Albania",
    "andorra": "Andorra",
    "armenia": "Armenia",
    "armenien": "Armenia",
    "austria": "Austria",
    "azerbaijan": "Azerbaijan",
    "aserbaidschan": "Azerbaijan",
    "belarus": "Belarus",
    "belgien": "Belgium",
    "belgium": "Belgium",
    "bosnia and herzegovina": "Bosnia and Herzegovina",
    "bosnien und herzegowina": "Bosnia and Herzegovina",
    "bulgaria": "Bulgaria",
    "bulgarien": "Bulgaria",
    "croatia": "Croatia",
    "czech republic": "Czech Republic",
    "czechia": "Czech Republic",
    "daenemark": "Denmark",
    "danemark": "Denmark",
    "denmark": "Denmark",
    "deutschland": "Germany",
    "england": "United Kingdom",
    "estland": "Estonia",
    "estonia": "Estonia",
    "finnland": "Finland",
    "finland": "Finland",
    "faroe islands": "Faroe Islands",
    "faroer": "Faroe Islands",
    "faroer inseln": "Faroe Islands",
    "france": "France",
    "frankreich": "France",
    "georgia": "Georgia",
    "germany": "Germany",
    "gibraltar": "Gibraltar",
    "greece": "Greece",
    "griechenland": "Greece",
    "grossbritannien": "United Kingdom",
    "guernsey": "Guernsey",
    "holland": "Netherlands",
    "hungary": "Hungary",
    "ungarn": "Hungary",
    "iceland": "Iceland",
    "island": "Iceland",
    "ireland": "Ireland",
    "irland": "Ireland",
    "isle of man": "Isle of Man",
    "italien": "Italy",
    "italy": "Italy",
    "kazakhstan": "Kazakhstan",
    "kasachstan": "Kazakhstan",
    "kroatien": "Croatia",
    "kosovo": "Kosovo",
    "lettland": "Latvia",
    "latvia": "Latvia",
    "liechtenstein": "Liechtenstein",
    "litauen": "Lithuania",
    "lithuania": "Lithuania",
    "luxembourg": "Luxembourg",
    "luxemburg": "Luxembourg",
    "malta": "Malta",
    "moldau": "Moldova",
    "moldawien": "Moldova",
    "moldavia": "Moldova",
    "moldova": "Moldova",
    "monaco": "Monaco",
    "montenegro": "Montenegro",
    "netherlands": "Netherlands",
    "niederlande": "Netherlands",
    "north macedonia": "North Macedonia",
    "nordmazedonien": "North Macedonia",
    "norway": "Norway",
    "norwegen": "Norway",
    "oesterreich": "Austria",
    "osterreich": "Austria",
    "poland": "Poland",
    "polen": "Poland",
    "portugal": "Portugal",
    "republic of moldova": "Moldova",
    "republik moldau": "Moldova",
    "romania": "Romania",
    "rumanien": "Romania",
    "rumaenien": "Romania",
    "russia": "Russia",
    "russland": "Russia",
    "san marino": "San Marino",
    "serbia": "Serbia",
    "serbien": "Serbia",
    "schweden": "Sweden",
    "schweiz": "Switzerland",
    "slovakia": "Slovakia",
    "slovak republic": "Slovakia",
    "slovakei": "Slovakia",
    "slovenia": "Slovenia",
    "slowenien": "Slovenia",
    "spain": "Spain",
    "spanien": "Spain",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "tschechien": "Czech Republic",
    "tschechische republik": "Czech Republic",
    "turkey": "Turkey",
    "turkei": "Turkey",
    "tuerkei": "Turkey",
    "ukraine": "Ukraine",
    "united kingdom": "United Kingdom",
    "vatican city": "Vatican City",
    "vatikan": "Vatican City",
    "vatikanstadt": "Vatican City",
    "vereinigtes konigreich": "United Kingdom",
    "vereinigtes koenigreich": "United Kingdom",
    "weissrussland": "Belarus",
}

_COUNTRY_COMPLETION_ALIASES = {
    "Dänemark",
    "Färöer-Inseln",
    "Großbritannien",
    "Österreich",
    "Rumänien",
    "Türkei",
    "Weißrussland",
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


def country_names_en() -> tuple[str, ...]:
    """Return canonical English country names for recipient-entry controls."""
    return tuple(sorted(set(_COUNTRY_BY_CODE.values())))


def country_search_names() -> tuple[str, ...]:
    """Return English and localized aliases suitable for country completion."""
    names = set(country_names_en())
    names.update(name.title() for name in _COUNTRY_BY_NAME)
    names.update(_COUNTRY_COMPLETION_ALIASES)
    return tuple(sorted(names, key=lambda value: (value.casefold(), value)))


def country_iso2(value: object) -> str:
    """Return an ISO-3166 alpha-2 code where the country is known.

    Carrier APIs require codes, whereas Wix and sevDesk frequently provide a
    localized country name (for example ``AUSTRIA`` or ``Oesterreich``).
    Unknown values deliberately return an empty string instead of producing a
    plausible but invalid two-character abbreviation.
    """
    text = _extract_text(value).strip()
    if not text:
        return ""
    upper = text.upper()
    if len(upper) == 2 and upper in _COUNTRY_BY_CODE:
        return upper

    canonical_name = country_name_en(text)
    canonical_key = normalized_country_key(canonical_name)
    for code, name in _COUNTRY_BY_CODE.items():
        if len(code) == 2 and normalized_country_key(name) == canonical_key:
            return code
    return ""


def country_label_for_address(value: object) -> str:
    """Return the printable country label used on physical address labels."""
    return country_name_en(value).upper()
