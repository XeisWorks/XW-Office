"""Pure tax follow-up models and deterministic mail contracts."""
from __future__ import annotations

import calendar
import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import stdnum.bic
import stdnum.iban

TAX_MAIL_SENDER = "office@xeisworks.at"
SEVDESK_AUTBOX = "autobox@sevdesk.email"
XW_FLOW_TRANSFER = "transfer@xeisworks.at"
_CENT = Decimal("0.01")


def money(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0").strip().replace(",", ".")).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Ungültiger Geldbetrag.") from exc


def calculation_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(repr(sorted((str(k), str(v)) for k, v in payload.items())).encode()).hexdigest()


@dataclass(frozen=True)
class TaxPayment:
    filing_kind: str
    period: str
    calculation_hash: str
    recipient: str
    iban: str
    bic: str
    amount: Decimal
    remittance: str
    due_date: str
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if self.amount <= 0 or self.currency != "EUR":
            raise ValueError("Zahlbetrag muss positiv und in EUR sein.")
        if not self.recipient.strip() or not self.iban.strip() or not self.remittance.strip():
            raise ValueError("Zahlungsempfänger, IBAN und Verwendungszweck sind erforderlich.")
        if len(self.recipient) > 140 or len(self.remittance) > 140:
            raise ValueError("Zahlungsempfänger und Verwendungszweck dürfen höchstens 140 Zeichen enthalten.")
        if not stdnum.iban.is_valid(self.iban.replace(" ", "").upper()):
            raise ValueError("IBAN ist ungültig.")
        if self.bic and not stdnum.bic.is_valid(self.bic.replace(" ", "").upper()):
            raise ValueError("BIC ist ungültig.")


def uva_payment(*, period: str, calculation_hash_value: str, recipient: str, iban: str,
                bic: str, zahlbetrag: object, remittance: str, due_date: str) -> TaxPayment | None:
    amount = money(zahlbetrag)
    if amount <= 0:
        return None
    return TaxPayment("uva", period, calculation_hash_value, recipient, iban, bic, amount, remittance, due_date)


def build_transfer_body(payment: TaxPayment, *, reference: str = "") -> str:
    lines = [
        "XW-Payment-Version: 1",
        f"XW-Payment-Key: tax:{payment.filing_kind}:{payment.period}:{payment.calculation_hash}",
        f"Art: {'EU-OSS' if payment.filing_kind == 'eu_oss' else payment.filing_kind.upper()}",
        f"Periode: {payment.period}", f"Empfänger: {payment.recipient}", f"IBAN: {payment.iban}",
        f"BIC: {payment.bic}", f"Gesamtbetrag: {payment.amount:.2f} EUR",
        f"Verwendungszweck: {payment.remittance}", f"Rechnung Nr.: {payment.filing_kind.upper()}-{payment.period}",
        f"Fällig: {payment.due_date}",
    ]
    if reference:
        lines.append(f"FinanzOnline-Referenz: {reference}")
    return "\n".join(lines)


def build_sevdesk_body(filing_kind: str, period: str, reference: str) -> str:
    return f"{filing_kind.upper()}-Bericht für {period}.\nFinanzOnline-Übermittlung erfolgreich.\nReferenz: {reference}"


def validate_tax_recipient(recipient: str) -> str:
    value = recipient.strip().lower()
    if value not in {SEVDESK_AUTBOX, XW_FLOW_TRANSFER}:
        raise ValueError("Steuermail-Empfänger ist nicht freigegeben.")
    return value


def _tax_number(value: str) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits if len(digits) == 9 else ""


def build_uva_payment_reference(year: int, month: int, tax_number: str) -> str:
    """Build the historic Finanzamt reference shape for a monthly UVA."""
    number = _tax_number(tax_number)
    if not number or not 1 <= int(month) <= 12 or not 2000 <= int(year) <= 2099:
        return ""
    return f"{int(year) % 100:02d}{int(month):02d}+{number}U"


def build_oss_payment_reference(year: int, quarter: int, tax_number: str) -> str:
    """Build the historic Finanzamt reference shape for an EU-OSS quarter."""
    number = _tax_number(tax_number)
    if not number or not 1 <= int(quarter) <= 4 or not 2000 <= int(year) <= 2099:
        return ""
    start_month = (int(quarter) - 1) * 3 + 1
    return f"{int(year) % 100:02d}{start_month:02d}/{start_month + 2:02d}+{number}UU"


def build_uva_payment_due_date(year: int, month: int) -> str:
    """Return the standard Austrian UVA payment date (15th of month + 2)."""
    if not 1 <= int(month) <= 12 or not 2000 <= int(year) <= 2099:
        return ""
    due_month = int(month) + 2
    due_year = int(year) + (due_month - 1) // 12
    due_month = (due_month - 1) % 12 + 1
    return date(due_year, due_month, 15).isoformat()


def build_oss_payment_due_date(year: int, quarter: int) -> str:
    """Return the EU-OSS due date, one month after the quarter end."""
    if not 1 <= int(quarter) <= 4 or not 2000 <= int(year) <= 2099:
        return ""
    due_month = int(quarter) * 3 + 1
    due_year = int(year) + (due_month - 1) // 12
    due_month = (due_month - 1) % 12 + 1
    return date(due_year, due_month, calendar.monthrange(due_year, due_month)[1]).isoformat()
