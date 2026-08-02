from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
import time
from typing import Iterable

DEFAULT_PLC_IMPORT_DIR = r"C:\ondot\ShipmentImport"
DEFAULT_TEST_PLC_IMPORT_DIR = r"C:\ondot\ShipmentImport_TEST"


@dataclass(frozen=True)
class PlcConfig:
    mode: str
    import_dir: str
    encoding: str = "windows-1252"
    delimiter: str = "|"


@dataclass(frozen=True)
class ShipmentAddress:
    company: str = ""
    name1: str = ""
    name2: str = ""
    name3: str = ""
    street: str = ""
    house_no: str = ""
    addr2: str = ""
    zip: str = ""
    city: str = ""
    country_iso2: str = ""
    phone: str = ""
    email: str = ""
    province_iso: str = ""
    eori: str = ""


def normalize_shipment_address(address: ShipmentAddress) -> ShipmentAddress:
    street = str(address.street or "").strip()
    house_no = str(address.house_no or "").strip()
    addr2 = str(address.addr2 or "").strip()
    if not addr2 or not _should_inline_address_addition(addr2):
        if street == address.street and house_no == address.house_no and addr2 == address.addr2:
            return address
        return replace(address, street=street, house_no=house_no, addr2=addr2)
    if house_no:
        house_no = f"{house_no} {addr2}".strip()
    elif street:
        house_no = addr2
    else:
        street = addr2
    return replace(address, street=street, house_no=house_no, addr2="")


def _should_inline_address_addition(addition: str) -> bool:
    text = str(addition or "").strip()
    if not text:
        return False
    if any(char.isalpha() for char in text):
        return False
    return bool(re.fullmatch(r"[0-9\s/\\\-.,;:+()#]+", text))


def normalize_weight(value: str | float | int | None, *, decimal_comma: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        formatted = f"{value:.3f}".rstrip("0").rstrip(".")
        return formatted.replace(".", ",") if decimal_comma else formatted
    text = str(value).strip().replace(",", ".")
    if not text:
        return ""
    number = float(text)
    formatted = f"{number:.3f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",") if decimal_comma else formatted


def format_amount(value: str | float | int | None, *, decimals: int = 2, decimal_comma: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        formatted = f"{float(value):.{decimals}f}"
        return formatted.replace(".", ",") if decimal_comma else formatted
    text = str(value).strip().replace(",", ".")
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return ""
    formatted = f"{number:.{decimals}f}"
    return formatted.replace(".", ",") if decimal_comma else formatted


def build_postdefaultport_lines(
    config: PlcConfig,
    *,
    product_id: str,
    address: ShipmentAddress,
    parcels: list[dict],
    metadata: dict | None = None,
    articles: list[dict] | None = None,
) -> list[str]:
    meta = metadata or {}
    delimiter = config.delimiter or "|"
    normalized = normalize_shipment_address(address)

    name1, name2, name3 = _resolve_recipient_name_lines(normalized)
    s_fields = [""] * 25
    s_fields[0] = str(product_id or "").strip()
    s_fields[1] = name1
    s_fields[2] = name2
    s_fields[3] = name3
    s_fields[5] = normalized.street
    s_fields[6] = normalized.house_no
    s_fields[7] = normalized.addr2
    s_fields[8] = normalized.zip
    s_fields[9] = normalized.city
    s_fields[10] = normalized.country_iso2
    s_fields[11] = normalized.phone
    s_fields[12] = normalized.email
    s_fields[13] = str(meta.get("shipment_id") or meta.get("number") or "").strip()
    s_fields[14] = str(meta.get("ref1") or "").strip()
    s_fields[15] = str(meta.get("ref2") or "").strip()
    s_fields[16] = str(meta.get("note") or "").strip()
    s_fields[17] = str(meta.get("customs_description") or "").strip()
    s_fields[19] = str(meta.get("returnsend") or "0").strip()
    s_fields[23] = str(meta.get("province_iso") or normalized.province_iso or "").strip()
    s_fields[24] = str(meta.get("eori") or normalized.eori or "").strip()

    lines = [delimiter.join(["S", *s_fields])]

    for parcel in parcels or []:
        c_fields = [""] * 4
        c_fields[0] = str(parcel.get("pakettyp") or "").strip()
        c_fields[1] = normalize_weight(parcel.get("gewicht"), decimal_comma=True)
        c_fields[2] = str(parcel.get("referenz") or "").strip()
        lines.append(delimiter.join(["C", *c_fields]))

    for article in articles or []:
        a_fields = [""] * 11
        a_fields[0] = str(article.get("sku") or "").strip()
        a_fields[1] = str(article.get("content") or "").strip()
        a_fields[2] = str(article.get("origin") or "").strip()
        a_fields[3] = str(article.get("hs_code") or "").strip()
        a_fields[4] = str(article.get("customs_type") or "").strip()
        a_fields[5] = str(article.get("description") or "").strip()
        qty = article.get("quantity")
        if isinstance(qty, (int, float)):
            qty = int(qty)
        a_fields[6] = str(qty or "").strip()
        a_fields[7] = str(article.get("unit") or "").strip()
        a_fields[8] = normalize_weight(article.get("net_weight_kg"), decimal_comma=True)
        a_fields[9] = format_amount(article.get("customs_value"), decimals=2, decimal_comma=True)
        a_fields[10] = str(article.get("currency") or "").strip()
        lines.append(delimiter.join(["A", *a_fields]))

    return lines


def _resolve_recipient_name_lines(address: ShipmentAddress) -> tuple[str, str, str]:
    company = str(address.company or "").strip()
    name1 = str(address.name1 or "").strip()
    name2 = str(address.name2 or "").strip()
    name3 = str(address.name3 or "").strip()
    if not company:
        return name1, name2, name3

    def _norm(text: str) -> str:
        return " ".join(text.lower().split())

    company_norm = _norm(company)
    person_line = ""
    for candidate in (name2, name1, name3):
        if candidate and _norm(candidate) != company_norm:
            person_line = candidate
            break
    third_line = name3
    if person_line and _norm(third_line) == _norm(person_line):
        third_line = ""
    if third_line and _norm(third_line) == company_norm:
        third_line = ""
    return company, person_line, third_line


def write_import_file(lines: Iterable[str], import_dir: str, filename_prefix: str, encoding: str = "windows-1252") -> Path:
    target_dir = Path(import_dir)
    if not target_dir.exists() or not target_dir.is_dir():
        raise FileNotFoundError(f"PLC Import-Ordner nicht gefunden: {import_dir}")
    if not os.access(str(target_dir), os.W_OK):
        raise PermissionError(f"PLC Import-Ordner nicht beschreibbar: {import_dir}")

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_prefix = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in filename_prefix or "plc")
    filename = f"{safe_prefix}_{timestamp}.csv"
    tmp_path = target_dir / f".{filename}.tmp"
    final_path = target_dir / filename
    payload = "\r\n".join(lines)
    tmp_path.write_text(payload, encoding=encoding, newline="")
    os.replace(tmp_path, final_path)
    return final_path
