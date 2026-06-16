"""Phase-2 UVA payload construction from the monthly preview groups."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from xw_studio.services.finanzonline.uva_models import UvaKennzahlen, UvaPayloadResult
from xw_studio.services.finanzonline.uva_preview import UvaPreviewGroup, UvaPreviewResult, UvaPreviewService

_DECIMAL_2 = Decimal("0.01")
_FOREIGN_MARKERS = (
    "DEUTSCHE",
    "ITALIENISCHE",
    "SPANISCHE",
    "FRANZÖSISCHE",
    "FRANZOESISCHE",
    "LUXEMBURGISCHE",
    "SCHWEDISCHE",
    "NIEDERLÄNDISCHE",
    "NIEDERLAENDISCHE",
    "BELGISCHE",
    "FINNISCHE",
    "DÄNISCHE",
    "DAENISCHE",
    "SLOWENISCHE",
    "TSCHECHISCHE",
    "IVA",
    "TVA",
    "MOMS",
    "BTW",
    "PVM",
    "DPH",
    "DDV",
)


class UvaPayloadService:
    """Convert preview groups into simplified U30 kennzahlen."""

    def __init__(self, preview_service: UvaPreviewService) -> None:
        self._preview_service = preview_service

    def build_payload(self, year: int, month: int) -> UvaPayloadResult:
        preview = self._preview_service.build_preview(year, month)
        return self.build_payload_from_preview(preview)

    def build_payload_from_preview(self, preview: UvaPreviewResult) -> UvaPayloadResult:
        values: dict[str, Decimal] = {key: Decimal("0.00") for key in UvaKennzahlen.model_fields}
        warnings: list[str] = list(preview.warnings)

        for group in preview.sales.groups:
            self._apply_sales_group(group, values, warnings)
        for group in preview.input_tax.groups:
            self._apply_purchase_group(group, values, warnings)

        values["A000"] = (
            values["A011"]
            + values["A017"]
            + values["A021"]
            + values["A022"]
            + values["A029"]
            + values["A006"]
        ).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)

        output_vat = (
            values["A022"] * Decimal("0.20")
            + values["A029"] * Decimal("0.10")
            + values["A006"] * Decimal("0.13")
            + values["A057"]
            + (values["B072"] * Decimal("0.20"))
        )
        input_vat = values["C060"] + values["C065"] + values["C066"]
        zahlbetrag = (output_vat - input_vat).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)

        kennzahlen = UvaKennzahlen(**{key: _fmt(value) for key, value in values.items()})
        return UvaPayloadResult(
            year=preview.year,
            month=preview.month,
            kennzahlen=kennzahlen,
            zahlbetrag=_fmt(zahlbetrag),
            warnings=warnings,
        )

    def render_kennzahlen_text(self, payload: UvaPayloadResult) -> str:
        kz = payload.kennzahlen
        lines = [
            "",
            "UVA-Kennzahlen",
            f"A000: EUR {_euro(kz.A000)}",
            f"A011: EUR {_euro(kz.A011)}",
            f"A017: EUR {_euro(kz.A017)}",
            f"A021: EUR {_euro(kz.A021)}",
            f"A022: EUR {_euro(kz.A022)}",
            f"A029: EUR {_euro(kz.A029)}",
            f"A006: EUR {_euro(kz.A006)}",
            f"A057: EUR {_euro(kz.A057)}",
            f"B070: EUR {_euro(kz.B070)}",
            f"B072: EUR {_euro(kz.B072)}",
            f"C060: EUR {_euro(kz.C060)}",
            f"C065: EUR {_euro(kz.C065)}",
            f"C066: EUR {_euro(kz.C066)}",
            f"Zahllast: EUR {_euro(payload.zahlbetrag)}",
        ]
        if payload.warnings:
            lines.extend(["", "Hinweise:"])
            lines.extend(f"- {warning}" for warning in payload.warnings)
        return "\n".join(lines).strip()

    def _apply_sales_group(
        self,
        group: UvaPreviewGroup,
        values: dict[str, Decimal],
        warnings: list[str],
    ) -> None:
        label = group.label.upper()
        net = _dec(group.net_amount)
        if label.startswith("MIT 20%"):
            values["A022"] += net
            return
        if label.startswith("MIT 10%"):
            values["A029"] += net
            return
        if label.startswith("MIT 13%"):
            values["A006"] += net
            return
        if "INNERGEMEINSCHAFT" in label and "LIEFER" in label:
            values["A017"] += net
            return
        if "AUSFUHR" in label:
            values["A011"] += net
            return
        if "REVERSE CHARGE" in label:
            values["A021"] += net
            return
        if _is_foreign_label(label):
            warnings.append(f"Nicht in AT-UVA übernommen: {group.label}")

    def _apply_purchase_group(
        self,
        group: UvaPreviewGroup,
        values: dict[str, Decimal],
        warnings: list[str],
    ) -> None:
        label = group.label.upper()
        net = _dec(group.net_amount)
        vat = _dec(group.vat_amount)
        if label.startswith("MIT 20%") or label.startswith("MIT 10%") or label.startswith("MIT 13%"):
            values["C060"] += vat
            return
        if "INNERGEMEINSCHAFT" in label and "LIEFER" in label:
            values["B070"] += net
            values["B072"] += net
            values["C065"] += (net * Decimal("0.20")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
            return
        if "REVERSE CHARGE" in label:
            tax = (net * Decimal("0.20")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
            values["A057"] += tax
            values["C066"] += tax
            return
        if _is_foreign_label(label):
            warnings.append(f"Ausländische Vorsteuer nicht in AT-UVA übernommen: {group.label}")


def _dec(value: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ".")).quantize(_DECIMAL_2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(_DECIMAL_2, rounding=ROUND_HALF_UP):.2f}"


def _euro(value: str) -> str:
    amount = _dec(value)
    formatted = f"{amount:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", " ")


def _is_foreign_label(label: str) -> bool:
    return any(marker in label for marker in _FOREIGN_MARKERS)
