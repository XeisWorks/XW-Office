"""Unit coverage for the direct PLC transport and canonical shipment model."""
from __future__ import annotations

import base64

import pytest

from xw_office.services.plc.models import (
    PlcCustomsArticle,
    PlcParcel,
    PlcShipmentDraft,
    build_polling_lines,
    parse_shipment_address_lines,
    requires_customs_declaration,
)
from xw_office.services.plc.polling import PlcConfig, ShipmentAddress
from xw_office.services.plc.service import PlcDuplicateShipmentError, PlcShipmentService
from xw_office.services.plc.webservice import (
    PlcWebserviceClient,
    PlcWebserviceRejectedError,
    PlcWebserviceSettings,
    build_import_shipment_row,
    webservice_settings_from_secrets,
)


def _settings() -> PlcWebserviceSettings:
    return PlcWebserviceSettings(
        mode="TEST",
        client_id=1000000001,
        org_unit_id=1461448,
        org_unit_guid="cd96848d-6552-4653-a992-f0f411710fb4",
        wsdl_url="https://example.test/ShippingService.svc?wsdl",
        shipper=ShipmentAddress(
            name1="XeisWorks",
            street="Johnsbach",
            house_no="92",
            zip="8912",
            city="Admont",
            country_iso2="AT",
            email="office@example.test",
        ),
    )


def _shipment(*, country: str = "AT", articles: tuple[PlcCustomsArticle, ...] = ()) -> PlcShipmentDraft:
    return PlcShipmentDraft(
        reference="20856",
        invoice_id="127129418",
        invoice_number="RE-2026-001",
        mode="TEST",
        product_id="10" if country == "AT" else "70",
        recipient=ShipmentAddress(
            name1="Max Mustermann",
            street="Teststrasse",
            house_no="1",
            zip="1030",
            city="Wien",
            country_iso2=country,
            email="max@example.test",
        ),
        parcels=(PlcParcel(weight_kg=0.5, reference="20856"),),
        customs_description="Notenbücher" if articles else "",
        articles=articles,
    )


def test_address_parser_normalizes_wix_country_label_to_iso2() -> None:
    address = parse_shipment_address_lines(
        ["Max Mustermann", "Teststrasse 1", "1030 Wien", "AUSTRIA"],
        email="max@example.test",
    )

    assert address.country_iso2 == "AT"
    assert address.street == "Teststrasse"
    assert address.house_no == "1"
    assert address.email == "max@example.test"


def test_address_parser_keeps_multi_word_city_out_of_austrian_postal_code() -> None:
    address = parse_shipment_address_lines(
        ["Vollton", "Renate Pilshofer", "Kollroßdorf 29", "4362 Bad Kreuzen", "AUSTRIA"]
    )

    assert address.zip == "4362"
    assert address.city == "Bad Kreuzen"
    assert address.country_iso2 == "AT"
    assert address.street == "Kollroßdorf"
    assert address.house_no == "29"


@pytest.mark.parametrize(
    ("postal_city", "country", "expected_zip", "expected_city"),
    [
        ("CH-8000 Zürich", "SWITZERLAND", "8000", "Zürich"),
        ("SW1A 1AA London", "UNITED KINGDOM", "SW1A 1AA", "London"),
        ("1234 AB Amsterdam", "NETHERLANDS", "1234 AB", "Amsterdam"),
        ("1017ZD Amsterdam", "NETHERLANDS", "1017 ZD", "Amsterdam"),
    ],
)
def test_address_parser_supports_postal_codes_containing_prefixes_or_spaces(
    postal_city: str,
    country: str,
    expected_zip: str,
    expected_city: str,
) -> None:
    address = parse_shipment_address_lines(
        ["Max Mustermann", "Teststrasse 1", postal_city, country]
    )

    assert address.zip == expected_zip
    assert address.city == expected_city


def test_address_parser_accepts_compact_dutch_street_and_postcode_line() -> None:
    address = parse_shipment_address_lines(
        [
            "Max Mustermann",
            "Tweede Weteringplantsoen 21, 1017 ZD Amsterdam",
            "NETHERLANDS",
        ]
    )

    assert address.street == "Tweede Weteringplantsoen"
    assert address.house_no == "21"
    assert address.zip == "1017 ZD"
    assert address.city == "Amsterdam"
    assert address.country_iso2 == "NL"


def test_shipment_validation_rejects_postcode_that_does_not_match_country() -> None:
    shipment = _shipment()
    shipment = PlcShipmentDraft(
        **{
            **shipment.__dict__,
            "recipient": ShipmentAddress(
                **{**shipment.recipient.__dict__, "zip": "4362 Bad"}
            ),
        }
    )

    with pytest.raises(ValueError, match="passt nicht zum Zielland AT"):
        shipment.validate()


def test_test_settings_accept_the_existing_test_plc_environment_aliases() -> None:
    class Secrets:
        values = {
            "TEST_PLC_CLIENT_ID": "12",
            "TEST_PLC_ORG_UNIT_ID": "3456789",
            "TEST_PLC_ORGUNIT_GUID": "cd96848d-6552-4653-a992-f0f411710fb4",
        }

        def get_secret(self, key: str) -> str:
            return self.values.get(key, "")

    settings = webservice_settings_from_secrets(Secrets(), mode="TEST")  # type: ignore[arg-type]

    assert settings.client_id == 12
    assert settings.org_unit_id == 3456789
    assert settings.org_unit_guid == "cd96848d-6552-4653-a992-f0f411710fb4"


def test_webservice_row_matches_local_plc_specification() -> None:
    row = build_import_shipment_row(_settings(), _shipment())

    assert row["ClientID"] == 1000000001
    assert row["OrgUnitID"] == 1461448
    assert row["DeliveryServiceThirdPartyID"] == "10"
    assert row["OURecipientAddress"] == {
        "Name1": "Max Mustermann",
        "Name2": "",
        "Name3": "",
        "AddressLine1": "Teststrasse",
        "AddressLine2": "",
        "HouseNumber": "1",
        "PostalCode": "1030",
        "City": "Wien",
        "CountryID": "AT",
        "Tel1": "",
        "Email": "max@example.test",
        "EORINumber": "",
        "ProvinceCode": "",
    }
    assert row["PrinterObject"] == {
        "LanguageID": "PDF",
        "LabelFormatID": "100x200",
        "PaperLayoutID": "A5",
    }
    assert row["ColloList"] == {"ColloRow": [{"Weight": 0.5}]}


def test_non_eu_shipment_requires_complete_customs_values() -> None:
    invalid = _shipment(country="CH")
    with pytest.raises(ValueError, match="Zoll"):
        invalid.validate()

    valid = _shipment(
        country="CH",
        articles=(
            PlcCustomsArticle(
                sku="XW-4582",
                name="Mnozil",
                quantity=1,
                net_weight_kg=0.3,
                customs_value_eur=19.9,
            ),
        ),
    )
    valid.validate()
    row = build_import_shipment_row(_settings(), valid)
    article = row["ColloList"]["ColloRow"][0]["ColloArticleList"]["ColloArticleRow"][0]  # type: ignore[index]
    assert article["HSTariffNumber"] == "49040000"
    assert article["ValueOfGoodsPerUnit"] == pytest.approx(19.9)
    assert article["DeclarationOfOrigin"] is False
    assert row["BusinessDocumentEntryList"] == {"string": ["CustomsDeclaration"]}


def test_webservice_sanitizes_plc_forbidden_customs_text_characters() -> None:
    shipment = _shipment(
        country="CH",
        articles=(
            PlcCustomsArticle(
                sku="XW-4582",
                name="Printed | sheet\nmusic – book",
                quantity=1,
                net_weight_kg=0.3,
                customs_value_eur=19.9,
            ),
        ),
    )

    row = build_import_shipment_row(_settings(), shipment)
    article = row["ColloList"]["ColloRow"][0]["ColloArticleList"]["ColloArticleRow"][0]  # type: ignore[index]

    assert article["ArticleName"] == "Printed sheet music - book"


def test_post_eu_exception_territories_require_customs() -> None:
    assert requires_customs_declaration("ES", postal_code="35001", city="Las Palmas")
    assert requires_customs_declaration("DE", postal_code="27498", city="Helgoland")
    assert not requires_customs_declaration("ES", postal_code="28001", city="Madrid")


def test_customs_net_weight_must_not_exceed_manual_package_gross_weight() -> None:
    shipment = _shipment(
        country="CH",
        articles=(
            PlcCustomsArticle(
                sku="XW-4582",
                name="Printed sheet music book",
                quantity=2,
                net_weight_kg=0.3,
                customs_value_eur=19.9,
            ),
        ),
    )

    with pytest.raises(ValueError, match="Nettogewicht"):
        shipment.validate()


def test_polling_fallback_uses_same_canonical_shipment_data() -> None:
    lines = build_polling_lines(PlcConfig(mode="TEST", import_dir="C:/ignored"), _shipment())

    assert lines[0].startswith("S|10|Max Mustermann")
    assert lines[0].endswith("|AT|") is False
    assert any(line.startswith("C|PC|0,5|20856") for line in lines)


def test_webservice_client_decodes_pdf_and_tracking_codes() -> None:
    pdf = b"%PDF-1.4\nlabel"
    customs_pdf = b"%PDF-1.4\nCN23"
    calls: list[dict[str, object]] = []

    class FakeSoap:
        def ImportShipment(self, *, row: dict[str, object]) -> object:  # noqa: N802
            calls.append(row)
            return {
                "pdfData": base64.b64encode(pdf).decode("ascii"),
                "shipmentDocuments": base64.b64encode(customs_pdf).decode("ascii"),
                "ImportShipmentResult": [{"ColloCodeList": [{"Code": "1000000500113230110301"}]}],
            }

    client = PlcWebserviceClient(service_factory=lambda _settings: FakeSoap())
    result = client.submit(_settings(), _shipment())

    assert result.pdf_bytes == pdf
    assert result.tracking_codes == ("1000000500113230110301",)
    assert result.shipment_documents == customs_pdf
    assert calls[0]["Number"] == "20856"


def test_webservice_client_surfaces_plc_business_error() -> None:
    class FakeSoap:
        def ImportShipment(self, *, row: dict[str, object]) -> object:  # noqa: N802, ARG002
            return {"errorCode": "SN#10035", "errorMessage": "Produkt nicht freigeschaltet"}

    client = PlcWebserviceClient(service_factory=lambda _settings: FakeSoap())
    with pytest.raises(PlcWebserviceRejectedError, match="SN#10035"):
        client.submit(_settings(), _shipment())


def test_service_suppresses_same_submission_in_memory() -> None:
    pdf = base64.b64encode(b"%PDF-1.4\nlabel").decode("ascii")

    class FakeSoap:
        calls = 0

        def ImportShipment(self, *, row: dict[str, object]) -> object:  # noqa: N802, ARG002
            self.calls += 1
            return {"pdfData": pdf}

    soap = FakeSoap()
    service = PlcShipmentService(PlcWebserviceClient(service_factory=lambda _settings: soap))
    shipment = _shipment()

    service.submit_webservice(_settings(), shipment)
    with pytest.raises(PlcDuplicateShipmentError):
        service.submit_webservice(_settings(), shipment)
    assert soap.calls == 1
