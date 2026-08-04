"""Canonical, transport-independent data model for Post Label Center."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Literal

from xw_office.services.plc.polling import ShipmentAddress, normalize_shipment_address
from xw_office.services.shipping.countries import country_iso2

PlcMode = Literal["LIVE", "TEST"]
PlcTransport = Literal["webservice", "polling"]

EU_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)


def requires_customs_declaration(
    country_iso2_value: object,
    *,
    postal_code: object = "",
    city: object = "",
) -> bool:
    """Return whether Post customs data is required for the destination."""
    code = str(country_iso2_value or "").strip().upper()
    if code not in EU_COUNTRIES:
        return bool(code)
    postal = re.sub(r"\s+", "", str(postal_code or "")).upper()
    city_key = str(city or "").strip().casefold()
    if code == "DE":
        return postal in {"27498", "78266"} or any(name in city_key for name in ("helgoland", "büsingen", "buesingen"))
    if code == "FI":
        return postal.startswith("22") or "åland" in city_key or "aland" in city_key
    if code == "GR":
        return postal == "63086" or any(name in city_key for name in ("athos", "agion oros"))
    if code == "IT":
        return postal in {"22061", "23041"} or any(name in city_key for name in ("campione", "livigno"))
    if code == "ES":
        return postal.startswith(("35", "38", "51", "52")) or any(
            name in city_key for name in ("ceuta", "melilla", "canarias", "canary")
        )
    return False


@dataclass(frozen=True)
class PlcParcel:
    """One physical parcel sent to PLC; weight is expressed in kilograms."""

    weight_kg: float
    package_type: str = "PC"
    reference: str = ""


@dataclass(frozen=True)
class PlcCustomsArticle:
    """Customs data required by PLC for non-EU destinations."""

    sku: str
    name: str
    quantity: int
    net_weight_kg: float
    customs_value_eur: float
    origin_iso2: str = "AT"
    hs_tariff_number: str = "49040000"
    unit_id: str = "PCE"
    currency: str = "EUR"
    customs_option_id: int = 1


@dataclass(frozen=True)
class PlcShipmentDraft:
    """Validated business data shared by the SOAP and file-import adapters."""

    reference: str
    invoice_id: str
    invoice_number: str
    mode: PlcMode
    product_id: str
    recipient: ShipmentAddress
    parcels: tuple[PlcParcel, ...]
    customs_description: str = ""
    articles: tuple[PlcCustomsArticle, ...] = field(default_factory=tuple)

    @property
    def country_iso2(self) -> str:
        return str(self.recipient.country_iso2 or "").upper().strip()

    @property
    def country_group(self) -> str:
        if self.country_iso2 == "AT":
            return "AT"
        if not requires_customs_declaration(
            self.country_iso2,
            postal_code=self.recipient.zip,
            city=self.recipient.city,
        ):
            return "EU"
        return "NON_EU"

    def request_fingerprint(self) -> str:
        """Stable hash used to suppress accidental repeat submissions."""
        payload = asdict(self)
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        recipient = normalize_shipment_address(self.recipient)
        missing = [
            label
            for label, value in (
                ("Referenz", self.reference),
                ("Versandprodukt", self.product_id),
                ("EmpfÃ¤nger", recipient.name1),
                ("StraÃŸe", recipient.street),
                ("Postleitzahl", recipient.zip),
                ("Ort", recipient.city),
                ("ISO-Land", recipient.country_iso2),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError("PLC-Sendung unvollstÃ¤ndig: " + ", ".join(missing))
        if len(str(recipient.country_iso2).strip()) != 2:
            raise ValueError("PLC-Land muss ein ISO-2-Code sein")
        if not self.parcels:
            raise ValueError("PLC-Sendung benÃ¶tigt mindestens ein Paket")
        for parcel in self.parcels:
            if float(parcel.weight_kg) <= 0:
                raise ValueError("PLC-Paketgewicht muss grÃ¶ÃŸer als 0 sein")
        if self.country_group == "NON_EU":
            if not self.customs_description.strip():
                raise ValueError("PLC-Zollbeschreibung fehlt")
            if not self.articles:
                raise ValueError("PLC-Zollartikel fehlen")
            for article in self.articles:
                if not article.name.strip() or article.quantity <= 0:
                    raise ValueError("PLC-Zollartikel unvollstÃ¤ndig")
                if article.net_weight_kg <= 0 or article.customs_value_eur <= 0:
                    raise ValueError("PLC-Zollartikel benÃ¶tigt Gewicht und Warenwert")
                if len(article.origin_iso2.strip()) != 2 or not article.hs_tariff_number.strip():
                    raise ValueError("PLC-Zollartikel benÃ¶tigt Ursprung und HS-Code")
                if not re.fullmatch(r"\d{6,10}", article.hs_tariff_number.strip()):
                    raise ValueError("PLC-Zolltarifnummer muss aus 6 bis 10 Ziffern bestehen")
                if not re.fullmatch(r"[A-Z]{3}", article.currency.strip().upper()):
                    raise ValueError("PLC-Zollartikel benötigt einen ISO-Währungscode")
            currencies = {article.currency.strip().upper() for article in self.articles}
            if len(currencies) != 1:
                raise ValueError("Alle PLC-Zollartikel müssen dieselbe Währung verwenden")


def clean_reference(value: object, *, max_length: int = 50) -> str:
    """Make a PLC-safe, human-readable reference without changing its meaning."""
    text = str(value or "").strip()
    text = re.sub(r"[\r\n|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def parse_shipment_address_lines(
    lines: list[str],
    *,
    fallback_name: str = "",
    email: str = "",
    phone: str = "",
) -> ShipmentAddress:
    """Parse the editable address preview while enforcing a real ISO country.

    It intentionally accepts localized Wix output such as ``AUSTRIA``.  The
    previous dialog forwarded those values verbatim, which is invalid for the
    PLC field ``CountryID``.
    """
    cleaned = [str(line or "").strip() for line in lines if str(line or "").strip()]
    country_raw = cleaned[-1] if cleaned else ""
    country = country_iso2(country_raw)
    postal_city = cleaned[-2] if len(cleaned) >= 2 else ""
    street_line = cleaned[-3] if len(cleaned) >= 3 else ""
    names = cleaned[:-3] if len(cleaned) >= 3 else cleaned[:1]

    zip_code = ""
    city = postal_city.strip()
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9 -]{1,14})\s+(.+)$", postal_city.strip())
    if match:
        zip_code = match.group(1).strip()
        city = match.group(2).strip()

    street = street_line.strip()
    house_no = ""
    street_match = re.match(r"^(.*?)(\d+[A-Za-z0-9\-/]*)$", street)
    if street_match:
        street = street_match.group(1).strip().rstrip(",")
        house_no = street_match.group(2).strip()

    return normalize_shipment_address(
        ShipmentAddress(
            name1=names[0] if names else str(fallback_name or "").strip(),
            name2=names[1] if len(names) > 1 else "",
            name3=names[2] if len(names) > 2 else "",
            street=street,
            house_no=house_no,
            zip=zip_code,
            city=city,
            country_iso2=country,
            email=str(email or "").strip(),
            phone=str(phone or "").strip(),
        )
    )


def build_polling_lines(config: object, shipment: PlcShipmentDraft) -> list[str]:
    """Render the legacy file-import syntax from the same canonical draft."""
    from xw_office.services.plc.polling import PlcConfig, build_postdefaultport_lines

    if not isinstance(config, PlcConfig):
        raise TypeError("PLC polling config has invalid type")
    shipment.validate()
    articles = [
        {
            "sku": article.sku,
            "content": article.name,
            "origin": article.origin_iso2,
            "hs_code": article.hs_tariff_number,
            "customs_type": "GOODS",
            "description": article.name,
            "quantity": article.quantity,
            "unit": article.unit_id,
            "net_weight_kg": article.net_weight_kg,
            "customs_value": article.customs_value_eur,
            "currency": article.currency,
        }
        for article in shipment.articles
    ]
    parcels = [
        {
            "pakettyp": parcel.package_type,
            "gewicht": parcel.weight_kg,
            "referenz": parcel.reference or shipment.reference,
        }
        for parcel in shipment.parcels
    ]
    return build_postdefaultport_lines(
        config,
        product_id=shipment.product_id,
        address=shipment.recipient,
        parcels=parcels,
        metadata={
            "shipment_id": shipment.reference,
            "ref1": shipment.reference,
            "ref2": shipment.invoice_number,
            "customs_description": shipment.customs_description,
            "returnsend": "0",
        },
        articles=articles,
    )
