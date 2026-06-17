"""FinanzOnline U30 XML generation and validation."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree as ET

try:
    from lxml import etree
except Exception:  # pragma: no cover - optional dependency guard
    etree = None

_DECIMAL_2 = Decimal("0.01")
_LEGACY_U30_XSD = (
    Path("C:/Users/bernh/GitHub/sevDesk/Finanzonline/xsd/u30")
    / "BMF_ERKLAERUNGS_UEBERMITTLUNG_U30_01_2022.xsd"
)


def default_u30_xsd_path() -> Path:
    return _LEGACY_U30_XSD


def parse_fastnr(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 9:
        raise ValueError("FINANZONLINE_FASTNR / FINANZONLINE_STEUERNUMMER muss 9-stellig sein.")
    return digits


def mask_fastnr(value: str) -> str:
    digits = parse_fastnr(value)
    return f"******{digits[-3:]}"


def build_u30_xml(payload: dict[str, Any], *, fastnr: str, created_at: datetime | None = None) -> str:
    safe_fastnr = parse_fastnr(fastnr)
    year = int(payload["jahr"])
    month = int(payload["monat"])
    kennzahlen = payload.get("kennzahlen")
    if not isinstance(kennzahlen, dict):
        raise ValueError("UVA-Payload enthaelt keine Kennzahlen.")

    now = created_at or datetime.now()
    period_text = f"{year:04d}-{month:02d}"
    root = ET.Element("ERKLAERUNGS_UEBERMITTLUNG")
    info = ET.SubElement(root, "INFO_DATEN")
    ET.SubElement(info, "ART_IDENTIFIKATIONSBEGRIFF").text = "FASTNR"
    ET.SubElement(info, "IDENTIFIKATIONSBEGRIFF").text = safe_fastnr
    ET.SubElement(info, "PAKET_NR").text = "1"
    date_node = ET.SubElement(info, "DATUM_ERSTELLUNG")
    date_node.set("type", "datum")
    date_node.text = now.strftime("%Y-%m-%d")
    time_node = ET.SubElement(info, "UHRZEIT_ERSTELLUNG")
    time_node.set("type", "uhrzeit")
    time_node.text = now.strftime("%H:%M:%S")
    ET.SubElement(info, "ANZAHL_ERKLAERUNGEN").text = "1"

    declaration = ET.SubElement(root, "ERKLAERUNG")
    declaration.set("art", "U30")
    ET.SubElement(declaration, "SATZNR").text = "1"
    general = ET.SubElement(declaration, "ALLGEMEINE_DATEN")
    ET.SubElement(general, "ANBRINGEN").text = "U30"
    zrvon = ET.SubElement(general, "ZRVON")
    zrvon.set("type", "jahrmonat")
    zrvon.text = period_text
    zrbis = ET.SubElement(general, "ZRBIS")
    zrbis.set("type", "jahrmonat")
    zrbis.text = period_text
    ET.SubElement(general, "FASTNR").text = safe_fastnr

    sales = ET.SubElement(declaration, "LIEFERUNGEN_LEISTUNGEN_EIGENVERBRAUCH")
    _add_kz(sales, "KZ000", kennzahlen.get("KZ000") or kennzahlen.get("A000"), allow_zero=True)
    _add_kz(sales, "KZ021", kennzahlen.get("KZ021") or kennzahlen.get("A021"))

    tax_free = {
        "KZ011": kennzahlen.get("KZ011") or kennzahlen.get("A011"),
        "KZ017": kennzahlen.get("KZ017") or kennzahlen.get("A017"),
    }
    if any(_amount(value) > Decimal("0.00") for value in tax_free.values()):
        node = ET.SubElement(sales, "STEUERFREI")
        for tag, value in tax_free.items():
            _add_kz(node, tag, value)

    taxed = {
        "KZ022": kennzahlen.get("KZ022") or kennzahlen.get("A022"),
        "KZ029": kennzahlen.get("KZ029") or kennzahlen.get("A029"),
        "KZ006": kennzahlen.get("KZ006") or kennzahlen.get("A006"),
        "KZ057": kennzahlen.get("KZ057") or kennzahlen.get("A057"),
    }
    if any(_amount(value) > Decimal("0.00") for value in taxed.values()):
        node = ET.SubElement(sales, "VERSTEUERT")
        for tag, value in taxed.items():
            _add_kz(node, tag, value)

    kz070 = kennzahlen.get("KZ070") or kennzahlen.get("B070")
    kz072 = kennzahlen.get("KZ072") or kennzahlen.get("B072")
    if _amount(kz070) > Decimal("0.00") or _amount(kz072) > Decimal("0.00"):
        acquisition = ET.SubElement(declaration, "INNERGEMEINSCHAFTLICHE_ERWERBE")
        _add_kz(acquisition, "KZ070", kz070, allow_zero=True)
        if _amount(kz072) > Decimal("0.00"):
            taxed_acquisition = ET.SubElement(acquisition, "VERSTEUERT_IGE")
            _add_kz(taxed_acquisition, "KZ072", kz072)

    input_tax = {
        "KZ060": kennzahlen.get("KZ060") or kennzahlen.get("C060"),
        "KZ065": kennzahlen.get("KZ065") or kennzahlen.get("C065"),
        "KZ066": kennzahlen.get("KZ066") or kennzahlen.get("C066"),
    }
    if any(_amount(value) > Decimal("0.00") for value in input_tax.values()):
        node = ET.SubElement(declaration, "VORSTEUER")
        for tag, value in input_tax.items():
            _add_kz(node, tag, value)

    return cast(str, ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8"))


def validate_u30_xml(xml_payload: str, xsd_path: str | Path | None = None) -> None:
    if etree is None:
        raise RuntimeError("lxml fehlt. XML-Validierung nicht moeglich.")
    path = Path(xsd_path or default_u30_xsd_path())
    if not path.exists():
        raise FileNotFoundError(f"U30-XSD nicht gefunden: {path}")
    schema_doc = etree.parse(str(path))
    schema = etree.XMLSchema(schema_doc)
    xml_doc = etree.fromstring(xml_payload.encode("utf-8"))
    if not schema.validate(xml_doc):
        errors = "\n".join(str(err) for err in schema.error_log)
        raise RuntimeError(f"U30-XSD-Validierung fehlgeschlagen:\n{errors}")


def _add_kz(parent: ET.Element, tag: str, value: object, *, allow_zero: bool = False) -> None:
    amount = _amount(value)
    if not allow_zero and abs(amount) < Decimal("0.005"):
        return
    if allow_zero and amount < Decimal("0.00"):
        return
    node = ET.SubElement(parent, tag)
    node.set("type", "kz")
    node.text = _format_amount(amount)


def _amount(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ".")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _format_amount(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"
