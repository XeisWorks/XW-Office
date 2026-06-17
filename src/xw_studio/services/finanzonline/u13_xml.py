"""FinanzOnline U13/ZM XML generation and validation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast
from xml.etree import ElementTree as ET

from xw_studio.services.finanzonline.u30_xml import parse_fastnr
from xw_studio.services.finanzonline.zm_service import ZmRow

try:
    from lxml import etree
except Exception:  # pragma: no cover - optional dependency guard
    etree = None

_LEGACY_U13_XSD = (
    Path("C:/Users/bernh/GitHub/sevDesk/Finanzonline/xsd/u13")
    / "BMF_XSD_Schema_Zusammenfassende_Meldung.xsd"
)


def default_u13_xsd_path() -> Path:
    return _LEGACY_U13_XSD


def build_u13_xml(
    *,
    year: int,
    month: int,
    rows: list[ZmRow],
    fastnr: str,
    kundeninfo: str | None = None,
    created_at: datetime | None = None,
) -> str:
    safe_fastnr = parse_fastnr(fastnr)
    if not rows:
        raise ValueError("ZM/U13 benoetigt mindestens eine Meldezeile.")

    period_text = f"{int(year):04d}-{int(month):02d}"
    now = created_at or datetime.now()
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
    declaration.set("art", "U13")
    ET.SubElement(declaration, "SATZNR").text = "1"

    general = ET.SubElement(declaration, "ALLGEMEINE_DATEN")
    ET.SubElement(general, "ANBRINGEN").text = "U13"
    zrvon = ET.SubElement(general, "ZRVON")
    zrvon.set("type", "jahrmonat")
    zrvon.text = period_text
    zrbis = ET.SubElement(general, "ZRBIS")
    zrbis.set("type", "jahrmonat")
    zrbis.text = period_text
    ET.SubElement(general, "FASTNR").text = safe_fastnr
    if kundeninfo:
        ET.SubElement(general, "KUNDENINFO").text = kundeninfo[:50]

    for row in sorted(rows, key=lambda item: (item.uid, item.kind)):
        node = ET.SubElement(declaration, "ZM")
        ET.SubElement(node, "UID_MS").text = row.uid
        amount = ET.SubElement(node, "SUM_BGL")
        amount.set("type", "kz")
        amount.text = str(int(row.amount_eur_int))
        if row.kind == "dreieck":
            ET.SubElement(node, "DREIECK").text = "J"
        elif row.kind == "service":
            ET.SubElement(node, "SOLEI").text = "J"

    return cast(str, ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8"))


def validate_u13_xml(xml_payload: str, xsd_path: str | Path | None = None) -> None:
    if etree is None:
        raise RuntimeError("lxml fehlt. XML-Validierung nicht moeglich.")
    path = Path(xsd_path or default_u13_xsd_path())
    if not path.exists():
        raise FileNotFoundError(f"U13-XSD nicht gefunden: {path}")
    schema_doc = etree.parse(str(path))
    schema = etree.XMLSchema(schema_doc)
    xml_doc = etree.fromstring(xml_payload.encode("utf-8"))
    if not schema.validate(xml_doc):
        errors = "\n".join(str(err) for err in schema.error_log)
        raise RuntimeError(f"U13-XSD-Validierung fehlgeschlagen:\n{errors}")
