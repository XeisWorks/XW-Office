from __future__ import annotations

from xw_studio.services.shipping.countries import country_label_for_address, country_name_en


def test_country_name_en_resolves_codes_and_german_names() -> None:
    assert country_name_en("AT") == "Austria"
    assert country_name_en("AUT") == "Austria"
    assert country_name_en("Österreich") == "Austria"
    assert country_name_en("Deutschland") == "Germany"
    assert country_name_en("Norwegen") == "Norway"


def test_country_label_for_address_is_english_uppercase() -> None:
    assert country_label_for_address("Norwegen") == "NORWAY"
    assert country_label_for_address({"countryCode": "CH"}) == "SWITZERLAND"
    assert country_label_for_address({"countryName": "Niederlande"}) == "NETHERLANDS"


def test_country_name_en_preserves_unknown_values() -> None:
    assert country_name_en("Atlantis") == "Atlantis"
    assert country_label_for_address("Atlantis") == "ATLANTIS"
