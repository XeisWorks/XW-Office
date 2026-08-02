"""Immutable UVA Golden-Master reference values."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


def default_uva_reference_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "uva_reference_values.json"


def load_uva_references(path: Path | str | None = None) -> Mapping[str, Mapping[str, Any]]:
    ref_path = Path(path) if path is not None else default_uva_reference_path()
    if not ref_path.exists():
        return MappingProxyType({})
    payload = json.loads(ref_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return MappingProxyType({})
    return _freeze_mapping(payload)


def compare_uva_reference(
    *,
    year: int,
    month: int,
    kennzahlen: dict[str, Any],
    zahlbetrag: Any,
    tolerance: Decimal = Decimal("0.10"),
    references: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    period = f"{int(year):04d}-{int(month):02d}"
    all_refs = references if references is not None else load_uva_references()
    reference = all_refs.get(period)
    if not isinstance(reference, Mapping):
        return {"period": period, "available": False, "deltas": [], "within_tolerance": None}

    reference_kz = reference.get("kennzahlen")
    deltas: list[dict[str, str]] = []
    if isinstance(reference_kz, Mapping):
        for key in sorted(reference_kz):
            expected = _decimal(reference_kz.get(key))
            actual = _decimal(kennzahlen.get(str(key)))
            delta = (actual - expected).quantize(Decimal("0.01"))
            deltas.append(
                {
                    "field": str(key),
                    "actual": f"{actual:.2f}",
                    "expected": f"{expected:.2f}",
                    "delta": f"{delta:.2f}",
                }
            )

    expected_amount = _decimal(reference.get("zahlbetrag"))
    actual_amount = _decimal(zahlbetrag)
    amount_delta = (actual_amount - expected_amount).quantize(Decimal("0.01"))
    within_tolerance = abs(amount_delta) <= tolerance
    return {
        "period": period,
        "available": True,
        "source": str(reference.get("source") or ""),
        "immutable_reference": bool(reference.get("immutable_reference")),
        "zahlbetrag": {
            "actual": f"{actual_amount:.2f}",
            "expected": f"{expected_amount:.2f}",
            "delta": f"{amount_delta:.2f}",
            "within_tolerance": within_tolerance,
            "tolerance": f"{tolerance:.2f}",
        },
        "deltas": deltas,
        "within_tolerance": within_tolerance,
    }


def render_reference_comparison_text(comparison: dict[str, Any]) -> str:
    if not comparison or not comparison.get("available"):
        return ""
    amount = comparison.get("zahlbetrag")
    lines = [
        "Golden-Master-Vergleich",
        f"Periode: {comparison.get('period') or '-'}",
    ]
    if isinstance(amount, dict):
        lines.append(
            "Zahllast: "
            f"Live EUR {amount.get('actual')}, "
            f"Soll EUR {amount.get('expected')}, "
            f"Delta EUR {amount.get('delta')}"
        )
    material = [
        row for row in comparison.get("deltas", [])
        if isinstance(row, dict) and _decimal(row.get("delta")) != Decimal("0.00")
    ]
    if material:
        lines.extend(["", "Kennzahlen mit Abweichung:"])
        for row in material[:12]:
            lines.append(
                f"- {row.get('field')}: Live {row.get('actual')} / "
                f"Soll {row.get('expected')} / Delta {row.get('delta')}"
            )
        if len(material) > 12:
            lines.append(f"- weitere Abweichungen: {len(material) - 12}")
    return "\n".join(lines)


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
