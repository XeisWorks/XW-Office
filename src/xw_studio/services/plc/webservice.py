"""Direct SOAP client for Austrian Post Label Center (PLC)."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import logging
import os
import time
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

from xw_studio.services.plc.models import PlcShipmentDraft
from xw_studio.services.plc.polling import ShipmentAddress, normalize_shipment_address
from xw_studio.services.shipping.countries import country_iso2

if TYPE_CHECKING:
    from xw_studio.services.secrets.service import SecretService

logger = logging.getLogger(__name__)

PLC_LIVE_WSDL = "https://plc.post.at/Post.Webservice/ShippingService.svc?wsdl"
PLC_TEST_WSDL = "https://abn-plc.post.at/DataService/Post.Webservice/ShippingService.svc?wsdl"


class PlcWebserviceError(RuntimeError):
    """Base error for a PLC direct-webservice operation."""


class PlcWebserviceRejectedError(PlcWebserviceError):
    """PLC processed the request and rejected it with a business error."""

    def __init__(self, error_code: str, error_message: str) -> None:
        self.error_code = str(error_code or "").strip()
        self.error_message = str(error_message or "").strip()
        message = ": ".join(part for part in (self.error_code, self.error_message) if part)
        super().__init__(message or "PLC hat die Sendung abgelehnt")


class PlcWebserviceTransportError(PlcWebserviceError):
    """Network/transport failure; the remote shipment state may be unknown."""


class _PlcSoapService(Protocol):
    def ImportShipment(self, *, row: dict[str, object]) -> object: ...  # noqa: N802 - SOAP operation name


SoapServiceFactory = Callable[["PlcWebserviceSettings"], _PlcSoapService]


@dataclass(frozen=True)
class PlcWebserviceSettings:
    """PLC credentials plus printer settings resolved at send time."""

    mode: str
    client_id: int | None
    org_unit_id: int | None
    org_unit_guid: str
    wsdl_url: str
    shipper: ShipmentAddress
    timeout_seconds: float = 45.0
    label_format_id: str = "100x200"
    paper_layout_id: str = "100x200"
    language_id: str = "PDF"

    @property
    def is_configured(self) -> bool:
        return not self.missing_fields()

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if self.client_id is None:
            missing.append("PLC_CLIENT_ID")
        if self.org_unit_id is None:
            missing.append("PLC_ORG_UNIT_ID")
        if not self.org_unit_guid:
            missing.append("PLC_ORG_UNIT_GUID")
        if not self.wsdl_url:
            missing.append("PLC-WSDL")
        normalized = normalize_shipment_address(self.shipper)
        for label, value in (
            ("PLC_SHIPPER_NAME1", normalized.name1),
            ("PLC_SHIPPER_STREET", normalized.street),
            ("PLC_SHIPPER_POSTAL_CODE", normalized.zip),
            ("PLC_SHIPPER_CITY", normalized.city),
            ("PLC_SHIPPER_COUNTRY", normalized.country_iso2),
        ):
            if not str(value or "").strip():
                missing.append(label)
        return missing

    def validate(self) -> None:
        missing = self.missing_fields()
        if missing:
            raise PlcWebserviceError("PLC-Webservice nicht konfiguriert: " + ", ".join(missing))
        if len(self.org_unit_guid.strip()) < 32:
            raise PlcWebserviceError("PLC_ORG_UNIT_GUID ist ungÃ¼ltig")
        if len(normalize_shipment_address(self.shipper).country_iso2.strip()) != 2:
            raise PlcWebserviceError("PLC_SHIPPER_COUNTRY muss ein ISO-2-Code sein")


@dataclass(frozen=True)
class PlcWebserviceResult:
    """Useful result fields returned by ``ImportShipment``."""

    pdf_bytes: bytes
    tracking_codes: tuple[str, ...]
    shipment_documents: bytes = b""


def webservice_settings_from_secrets(secrets: "SecretService", *, mode: str) -> PlcWebserviceSettings:
    """Build settings late so updates in Settings take effect without restart."""
    normalized_mode = "TEST" if str(mode or "").upper() == "TEST" else "LIVE"

    def value(name: str, *, test_fallback_to_live: bool = False) -> str:
        if normalized_mode == "TEST":
            test_value = secrets.get_secret(f"PLC_TEST_{name}")
            if test_value:
                return test_value
            if test_fallback_to_live:
                return secrets.get_secret(f"PLC_{name}")
        return secrets.get_secret(f"PLC_{name}")

    def integer(name: str) -> int | None:
        raw = value(name, test_fallback_to_live=True).strip()
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    wsdl_default = PLC_TEST_WSDL if normalized_mode == "TEST" else PLC_LIVE_WSDL
    wsdl_name = "TEST_WSDL_URL" if normalized_mode == "TEST" else "WSDL_URL"
    wsdl = secrets.get_secret(f"PLC_{wsdl_name}") or os.getenv(f"PLC_{wsdl_name}", "") or wsdl_default
    timeout_raw = secrets.get_secret("PLC_TIMEOUT_SECONDS") or os.getenv("PLC_TIMEOUT_SECONDS", "45")
    try:
        timeout = max(float(timeout_raw), 1.0)
    except ValueError:
        timeout = 45.0

    return PlcWebserviceSettings(
        mode=normalized_mode,
        client_id=integer("CLIENT_ID"),
        org_unit_id=integer("ORG_UNIT_ID"),
        org_unit_guid=value("ORG_UNIT_GUID", test_fallback_to_live=True).strip(),
        wsdl_url=str(wsdl).strip(),
        shipper=ShipmentAddress(
            name1=secrets.get_secret("PLC_SHIPPER_NAME1"),
            name2=secrets.get_secret("PLC_SHIPPER_NAME2"),
            street=secrets.get_secret("PLC_SHIPPER_STREET"),
            house_no=secrets.get_secret("PLC_SHIPPER_HOUSE_NUMBER"),
            addr2=secrets.get_secret("PLC_SHIPPER_ADDRESS_LINE2"),
            zip=secrets.get_secret("PLC_SHIPPER_POSTAL_CODE"),
            city=secrets.get_secret("PLC_SHIPPER_CITY"),
            country_iso2=country_iso2(secrets.get_secret("PLC_SHIPPER_COUNTRY")),
            phone=secrets.get_secret("PLC_SHIPPER_PHONE"),
            email=secrets.get_secret("PLC_SHIPPER_EMAIL"),
            eori=secrets.get_secret("PLC_SHIPPER_EORI"),
        ),
        timeout_seconds=timeout,
        label_format_id=(secrets.get_secret("PLC_LABEL_FORMAT_ID") or "100x200").strip(),
        paper_layout_id=(secrets.get_secret("PLC_PAPER_LAYOUT_ID") or "100x200").strip(),
        language_id=(secrets.get_secret("PLC_LABEL_LANGUAGE") or "PDF").strip().upper(),
    )


class PlcWebserviceClient:
    """Synchronous SOAP client. Call it only from a background worker."""

    def __init__(self, *, service_factory: SoapServiceFactory | None = None) -> None:
        self._service_factory = service_factory or _create_zeep_service

    def submit(self, settings: PlcWebserviceSettings, shipment: PlcShipmentDraft) -> PlcWebserviceResult:
        settings.validate()
        shipment.validate()
        payload = build_import_shipment_row(settings, shipment)
        started = time.perf_counter()
        try:
            response = self._service_factory(settings).ImportShipment(row=payload)
        except PlcWebserviceError:
            raise
        except Exception as exc:  # noqa: BLE001 - SOAP transport errors vary by Zeep backend.
            raise PlcWebserviceTransportError(f"PLC-Webservice nicht erreichbar: {exc}") from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        error_code = _response_value(response, "errorCode")
        error_message = _response_value(response, "errorMessage")
        if error_code or error_message:
            logger.warning(
                "PLC webservice rejected mode=%s product=%s elapsed_ms=%s code=%s",
                settings.mode,
                shipment.product_id,
                elapsed_ms,
                error_code or "-",
            )
            raise PlcWebserviceRejectedError(error_code, error_message)

        pdf_bytes = _decode_base64_field(_response_object(response, "pdfData"), field_name="pdfData")
        if not _looks_like_pdf(pdf_bytes):
            raise PlcWebserviceError("PLC lieferte kein gÃ¼ltiges PDF-Label")
        documents = _decode_base64_field(
            _response_object(response, "shipmentDocuments"),
            field_name="shipmentDocuments",
            allow_empty=True,
        )
        codes = tuple(_tracking_codes(response))
        logger.info(
            "PLC webservice success mode=%s product=%s elapsed_ms=%s tracking_count=%s pdf_bytes=%s",
            settings.mode,
            shipment.product_id,
            elapsed_ms,
            len(codes),
            len(pdf_bytes),
        )
        return PlcWebserviceResult(pdf_bytes=pdf_bytes, tracking_codes=codes, shipment_documents=documents)


def build_import_shipment_row(settings: PlcWebserviceSettings, shipment: PlcShipmentDraft) -> dict[str, object]:
    """Map the canonical draft to the local PLC API specification exactly."""
    recipient = normalize_shipment_address(shipment.recipient)
    shipper = normalize_shipment_address(settings.shipper)
    if shipment.country_group == "NON_EU" and len(shipment.parcels) != 1:
        raise ValueError("Nicht-EU-Sendungen mit mehreren Paketen benÃ¶tigen eine Paket-Zollaufteilung")
    if shipment.country_group == "NON_EU":
        if not (shipper.phone.strip() or shipper.email.strip()):
            raise ValueError("PLC-Zollsendung benÃ¶tigt Telefon oder E-Mail des Absenders")
        if not (recipient.phone.strip() or recipient.email.strip()):
            raise ValueError("PLC-Zollsendung benÃ¶tigt Telefon oder E-Mail des Empfängers")

    collo_list: list[dict[str, object]] = []
    for index, parcel in enumerate(shipment.parcels):
        collo: dict[str, object] = {"Weight": float(parcel.weight_kg)}
        if shipment.country_group == "NON_EU" and index == 0:
            collo["ColloArticleList"] = [_article_row(article) for article in shipment.articles]
        collo_list.append(collo)

    row: dict[str, object] = {
        "ClientID": settings.client_id,
        "OrgUnitID": settings.org_unit_id,
        "OrgUnitGuid": settings.org_unit_guid,
        "Number": shipment.reference,
        "DeliveryServiceThirdPartyID": shipment.product_id,
        "OUShipperReference1": shipment.reference,
        "OUShipperReference2": shipment.invoice_number,
        "CustomerProduct": "XW-Studio",
        "OURecipientAddress": _address_row(recipient),
        "OUShipperAddress": _address_row(shipper),
        "ColloList": collo_list,
        "PrinterObject": {
            "LanguageID": settings.language_id,
            "LabelFormatID": settings.label_format_id,
            "PaperLayoutID": settings.paper_layout_id,
        },
    }
    if shipment.customs_description.strip():
        row["CustomsDescription"] = shipment.customs_description.strip()
    return row


def _address_row(address: ShipmentAddress) -> dict[str, str]:
    normalized = normalize_shipment_address(address)
    return {
        "Name1": normalized.name1,
        "Name2": normalized.name2,
        "Name3": normalized.name3,
        "AddressLine1": normalized.street,
        "AddressLine2": normalized.addr2,
        "HouseNumber": normalized.house_no,
        "PostalCode": normalized.zip,
        "City": normalized.city,
        "CountryID": normalized.country_iso2.upper(),
        "Tel1": normalized.phone,
        "Email": normalized.email,
        "EORINumber": normalized.eori,
        "ProvinceCode": normalized.province_iso,
    }


def _article_row(article: object) -> dict[str, object]:
    from xw_studio.services.plc.models import PlcCustomsArticle

    if not isinstance(article, PlcCustomsArticle):
        raise TypeError("PLC customs article has invalid type")
    return {
        "ArticleNumber": article.sku,
        "ArticleName": article.name,
        "CountryOfOriginID": article.origin_iso2.upper(),
        "HSTariffNumber": article.hs_tariff_number,
        "CustomsOptionID": article.customs_option_id,
        "DeclarationOfOrigin": False,
        "Quantity": article.quantity,
        "UnitID": article.unit_id,
        "ConsumerUnitNetWeight": float(article.net_weight_kg),
        "ValueOfGoodsPerUnit": float(article.customs_value_eur),
        "CurrencyID": article.currency.upper(),
    }


def _create_zeep_service(settings: PlcWebserviceSettings) -> _PlcSoapService:
    """Create the WSDL client lazily so app start never performs network I/O."""
    try:
        import requests
        from zeep import Client, Settings
        from zeep.transports import Transport
    except ImportError as exc:  # pragma: no cover - covered by project dependency declaration.
        raise PlcWebserviceError("Zeep/requests fÃ¼r PLC-Webservice nicht installiert") from exc

    session = requests.Session()
    transport = Transport(
        session=session,
        timeout=settings.timeout_seconds,
        operation_timeout=settings.timeout_seconds,
    )
    client = Client(
        wsdl=settings.wsdl_url,
        transport=transport,
        settings=Settings(strict=False, xml_huge_tree=True),
    )
    return client.service  # type: ignore[return-value]


def _response_object(response: object, key: str) -> object:
    if isinstance(response, Mapping):
        return response.get(key)
    return getattr(response, key, None)


def _response_value(response: object, key: str) -> str:
    value = _response_object(response, key)
    return "" if value is None else str(value).strip()


def _tracking_codes(response: object) -> list[str]:
    result: object
    if isinstance(response, Mapping):
        result = response.get("ImportShipmentResult") or []
    else:
        result = getattr(response, "ImportShipmentResult", None) or []
    if not isinstance(result, (list, tuple)):
        result = [result]

    codes: list[str] = []
    for collo in result:
        values = collo.get("ColloCodeList") if isinstance(collo, Mapping) else getattr(collo, "ColloCodeList", None)
        if not isinstance(values, (list, tuple)):
            values = [values] if values is not None else []
        for code_row in values:
            value = code_row.get("Code") if isinstance(code_row, Mapping) else getattr(code_row, "Code", None)
            text = str(value or "").strip()
            if text and text not in codes:
                codes.append(text)
    return codes


def _decode_base64_field(value: object, *, field_name: str, allow_empty: bool = False) -> bytes:
    if value is None or value == "":
        if allow_empty:
            return b""
        raise PlcWebserviceError(f"PLC-Antwort enthÃ¤lt kein {field_name}")
    if isinstance(value, bytes):
        if value.startswith(b"%PDF-") or allow_empty:
            return value
        raw = value
    else:
        raw = str(value).encode("ascii")
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001 - include the field, never the payload.
        raise PlcWebserviceError(f"PLC-Antwort enthÃ¤lt ungÃ¼ltiges {field_name}") from exc


def _looks_like_pdf(payload: bytes) -> bool:
    return bool(payload and b"%PDF-" in payload[:1024])
