"""Immutable EU-OSS Golden-Master reference values."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from xw_studio.services.finanzonline.oss_models import OssQuarterResult


def default_oss_reference_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "oss_reference_values.json"


def load_oss_references(path: Path | str | None = None) -> Mapping[str, Mapping[str, Any]]:
    ref_path = Path(path) if path is not None else default_oss_reference_path()
    if not ref_path.exists():
        return MappingProxyType({})
    payload = json.loads(ref_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return MappingProxyType({})
    quarters = payload.get("quarters")
    if isinstance(quarters, dict):
        return _freeze_mapping(quarters)
    return _freeze_mapping(payload)


def compare_oss_reference(
    result: OssQuarterResult,
    *,
    tolerance: Decimal = Decimal("0.01"),
    references: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    period = f"{int(result.year):04d}-Q{int(result.quarter)}"
    all_refs = references if references is not None else load_oss_references()
    reference = all_refs.get(period)
    if not isinstance(reference, Mapping):
        return {"period": period, "available": False, "lines": [], "within_tolerance": None}

    actual = {
        (line.country_code, _decimal(line.vat_rate), bool(line.goods)): {
            "net": _decimal(line.taxable_amount),
            "vat": _decimal(line.tax_amount),
            "gross": (_decimal(line.taxable_amount) + _decimal(line.tax_amount)).quantize(Decimal("0.01")),
        }
        for line in [*result.goods_lines, *result.service_lines]
    }
    expected_rows = reference.get("lines")
    expected = {}
    if isinstance(expected_rows, (list, tuple)):
        for row in expected_rows:
            if not isinstance(row, Mapping):
                continue
            expected[(str(row.get("country_code") or ""), _decimal(row.get("vat_rate_label")), True)] = {
                "net": _decimal(row.get("net")),
                "vat": _decimal(row.get("vat")),
                "gross": _decimal(row.get("gross")),
                "label": str(row.get("label") or ""),
            }

    lines: list[dict[str, Any]] = []
    within_tolerance = True
    for key in sorted(set(actual) | set(expected), key=lambda item: (item[0], item[1], item[2])):
        actual_values = actual.get(key, {})
        expected_values = expected.get(key, {})
        net_delta = _decimal(actual_values.get("net")) - _decimal(expected_values.get("net"))
        vat_delta = _decimal(actual_values.get("vat")) - _decimal(expected_values.get("vat"))
        gross_delta = _decimal(actual_values.get("gross")) - _decimal(expected_values.get("gross"))
        row_within = all(abs(value) <= tolerance for value in (net_delta, vat_delta, gross_delta))
        within_tolerance = within_tolerance and row_within
        lines.append(
            {
                "country_code": key[0],
                "vat_rate": f"{key[1]:.2f}",
                "goods": key[2],
                "label": expected_values.get("label", ""),
                "actual_net": f"{_decimal(actual_values.get('net')):.2f}",
                "expected_net": f"{_decimal(expected_values.get('net')):.2f}",
                "delta_net": f"{net_delta:.2f}",
                "actual_vat": f"{_decimal(actual_values.get('vat')):.2f}",
                "expected_vat": f"{_decimal(expected_values.get('vat')):.2f}",
                "delta_vat": f"{vat_delta:.2f}",
                "actual_gross": f"{_decimal(actual_values.get('gross')):.2f}",
                "expected_gross": f"{_decimal(expected_values.get('gross')):.2f}",
                "delta_gross": f"{gross_delta:.2f}",
                "within_tolerance": row_within,
            }
        )

    return {
        "period": period,
        "available": True,
        "immutable_reference": bool(reference.get("immutable_reference")),
        "lines": lines,
        "within_tolerance": within_tolerance,
        "tolerance": f"{tolerance:.2f}",
    }


def _freeze_mapping(value: dict[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            frozen[str(key)] = _freeze_mapping(item)
        elif isinstance(item, list):
            frozen[str(key)] = tuple(item)
        else:
            frozen[str(key)] = item
    return MappingProxyType(frozen)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
