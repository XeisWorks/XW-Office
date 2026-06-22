from __future__ import annotations

import pytest

from xw_studio.services.shipping.countries import country_label_for_address, country_name_en


def test_country_name_en_resolves_codes_and_german_names() -> None:
    assert country_name_en("AT") == "Austria"
    assert country_name_en("AUT") == "Austria"
    assert country_name_en("Österreich") == "Austria"
    assert country_name_en("Deutschland") == "Germany"
    assert country_name_en("Norwegen") == "Norway"
    assert country_name_en("Tschechische Republik") == "Czech Republic"


def test_country_label_for_address_is_english_uppercase() -> None:
    assert country_label_for_address("Norwegen") == "NORWAY"
    assert country_label_for_address("Tschechische Republik") == "CZECH REPUBLIC"
    assert country_label_for_address({"countryCode": "CH"}) == "SWITZERLAND"
    assert country_label_for_address({"countryName": "Niederlande"}) == "NETHERLANDS"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AL", "Albania"),
        ("AD", "Andorra"),
        ("AM", "Armenia"),
        ("AZ", "Azerbaijan"),
        ("BY", "Belarus"),
        ("BA", "Bosnia and Herzegovina"),
        ("BG", "Bulgaria"),
        ("CY", "Cyprus"),
        ("DK", "Denmark"),
        ("EE", "Estonia"),
        ("FI", "Finland"),
        ("FR", "France"),
        ("GE", "Georgia"),
        ("GR", "Greece"),
        ("HU", "Hungary"),
        ("IS", "Iceland"),
        ("IE", "Ireland"),
        ("IT", "Italy"),
        ("KZ", "Kazakhstan"),
        ("XK", "Kosovo"),
        ("LI", "Liechtenstein"),
        ("LT", "Lithuania"),
        ("LU", "Luxembourg"),
        ("LV", "Latvia"),
        ("MT", "Malta"),
        ("MD", "Moldova"),
        ("MC", "Monaco"),
        ("ME", "Montenegro"),
        ("MK", "North Macedonia"),
        ("NL", "Netherlands"),
        ("NO", "Norway"),
        ("PL", "Poland"),
        ("PT", "Portugal"),
        ("RO", "Romania"),
        ("RU", "Russia"),
        ("SM", "San Marino"),
        ("RS", "Serbia"),
        ("SK", "Slovakia"),
        ("SI", "Slovenia"),
        ("ES", "Spain"),
        ("SE", "Sweden"),
        ("CH", "Switzerland"),
        ("TR", "Turkey"),
        ("UA", "Ukraine"),
        ("GB", "United Kingdom"),
        ("VA", "Vatican City"),
    ],
)
def test_country_name_en_resolves_european_country_codes(value: str, expected: str) -> None:
    assert country_name_en(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Albanien", "ALBANIA"),
        ("Aserbaidschan", "AZERBAIJAN"),
        ("Bosnien und Herzegowina", "BOSNIA AND HERZEGOVINA"),
        ("Bulgarien", "BULGARIA"),
        ("Weissrussland", "BELARUS"),
        ("Daenemark", "DENMARK"),
        ("Griechenland", "GREECE"),
        ("Grossbritannien", "UNITED KINGDOM"),
        ("Kasachstan", "KAZAKHSTAN"),
        ("Moldawien", "MOLDOVA"),
        ("Nordmazedonien", "NORTH MACEDONIA"),
        ("Polen", "POLAND"),
        ("Rumaenien", "ROMANIA"),
        ("Russland", "RUSSIA"),
        ("Spanien", "SPAIN"),
        ("Tuerkei", "TURKEY"),
        ("Vereinigtes Koenigreich", "UNITED KINGDOM"),
        ("Vatikanstadt", "VATICAN CITY"),
    ],
)
def test_country_label_for_address_resolves_common_german_european_names(
    value: str, expected: str
) -> None:
    assert country_label_for_address(value) == expected


def test_country_name_en_preserves_unknown_values() -> None:
    assert country_name_en("Atlantis") == "Atlantis"
    assert country_label_for_address("Atlantis") == "ATLANTIS"
