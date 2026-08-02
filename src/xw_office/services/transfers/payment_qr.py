from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import json
import logging
from pathlib import Path
import re
from typing import Any

import httpx
from pypdf import PdfReader
from segno import helpers
import stdnum.bic
import stdnum.iban

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    import fitz  # type: ignore
except Exception:  # pragma: no cover
    fitz = None

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None

from xw_office.services.transfers.models import TransferFieldSource, TransferPaymentData

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9 ]{10,40}\b")
_BIC_RE = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_LABELLED_BIC_RE = re.compile(r"\b(?:BIC|SWIFT)\s*:?\s*([A-Z0-9 ]{8,20})", re.IGNORECASE)
_INVOICE_RE = re.compile(
    r"\b(?:RE|RG|INV)(?:[-\s]*\d[A-Z0-9-]{2,}|[-\s]+[A-Z0-9-]{2,}\d[A-Z0-9-]*)\b",
    re.IGNORECASE,
)
_INVOICE_LABEL_RE = re.compile(
    r"\b(?:rechnungs(?:nummer|-?nr\.?)|rechnung\s+nr\.?|rechnung|beleg-?nr\.?|auftragsnr\.?)"
    r"\s*[:.]?\s*((?=[A-Z0-9/-]*\d)[A-Z0-9][A-Z0-9/-]{2,})\b",
    re.IGNORECASE,
)
_REMITTANCE_RE = re.compile(r"\b(?:verwendungszweck|vermerk)\s*:\s*([A-Z0-9][A-Z0-9/\- ]{2,80})", re.IGNORECASE)
_AMOUNT_KEYWORDS = (
    "gesamtbetrag brutto",
    "endbetrag",
    "gesamtpreis",
    "betrag von",
    "rechnungsbetrag",
    "zahlbetrag",
    "gesamtbetrag",
)


class PaymentQrError(RuntimeError):
    """Raised when payment extraction or QR creation fails."""


def _normalize_iban(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _parse_amount(value: str) -> Decimal | None:
    token = str(value or "").strip().replace("EUR", "").replace(" ", "")
    if not token:
        return None
    if "," in token and "." in token:
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(token)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _find_valid_iban(text: str) -> str:
    for match in _IBAN_RE.finditer(str(text or "").upper()):
        candidate = _normalize_iban(match.group(0))
        for length in range(min(len(candidate), 34), 14, -1):
            trimmed = candidate[:length]
            if stdnum.iban.is_valid(trimmed):
                return trimmed
    return ""


def _find_valid_bic(text: str) -> str:
    for label_match in _LABELLED_BIC_RE.finditer(str(text or "").upper()):
        for match in _BIC_RE.finditer(label_match.group(1)):
            candidate = match.group(0).strip().upper()
            if stdnum.bic.is_valid(candidate):
                return candidate
    return ""


def _normalize_valid_bic(value: str) -> str:
    match = _BIC_RE.search(str(value or "").upper())
    if not match:
        return ""
    candidate = match.group(0).strip().upper()
    return candidate if stdnum.bic.is_valid(candidate) else ""


def _extract_amount_from_text(text: str) -> Decimal | None:
    hay = str(text or "")
    lowered = hay.lower()
    for keyword in _AMOUNT_KEYWORDS:
        start = 0
        found: Decimal | None = None
        while True:
            idx = lowered.find(keyword, start)
            if idx < 0:
                break
            window = hay[idx : idx + 140]
            matches = list(_AMOUNT_RE.finditer(window))
            if matches:
                parsed = _parse_amount(matches[-1].group(1))
                if parsed is not None:
                    found = parsed
            start = idx + len(keyword)
        if found is not None:
            return found
    return None


def _extract_invoice_number(text: str) -> str:
    hay = str(text or "")
    label_match = _INVOICE_LABEL_RE.search(hay)
    if label_match:
        return label_match.group(1).strip(" .:-")
    invoice_match = _INVOICE_RE.search(hay)
    if invoice_match:
        return invoice_match.group(0).strip()
    return ""


def _extract_remittance(text: str) -> str:
    match = _REMITTANCE_RE.search(str(text or ""))
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip(" .:-")


def _validate_payment(payment: TransferPaymentData) -> None:
    if not str(payment.recipient or "").strip():
        raise PaymentQrError("Empfaenger fehlt.")
    if len(str(payment.recipient)) > 70:
        raise PaymentQrError("Empfaenger darf maximal 70 Zeichen lang sein.")
    iban = _normalize_iban(payment.iban)
    if not iban or not stdnum.iban.is_valid(iban):
        raise PaymentQrError("IBAN ist ungueltig.")
    payment.iban = iban
    bic = str(payment.bic or "").strip().upper()
    if bic and not stdnum.bic.is_valid(bic):
        raise PaymentQrError("BIC ist ungueltig.")
    payment.bic = bic
    if payment.amount is None or payment.amount <= Decimal("0"):
        raise PaymentQrError("Betrag muss groesser als 0 sein.")
    payment.amount = payment.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    payment.currency = "EUR"
    remittance = str(payment.remittance_text or "").strip()
    if not remittance and str(payment.invoice_number or "").strip():
        remittance = str(payment.invoice_number).strip()
    if len(remittance) > 140:
        raise PaymentQrError("Verwendungszweck darf maximal 140 Zeichen lang sein.")
    payment.remittance_text = remittance


def _is_structured_epc_reference(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and "\n" not in text and "\r" not in text and len(text) <= 35)


def _prefer_invoice_number_for_remittance(payment: TransferPaymentData) -> None:
    if payment.source_by_field.get("remittance_text") == TransferFieldSource.PDF_EXISTING_QR:
        return
    invoice_number = str(payment.invoice_number or "").strip()
    if not invoice_number:
        return
    payment.remittance_text = invoice_number
    payment.source_by_field["remittance_text"] = payment.source_by_field.get(
        "invoice_number",
        TransferFieldSource.UNKNOWN,
    )


def _extract_from_text(text: str) -> TransferPaymentData:
    out = TransferPaymentData()
    if not text:
        return out
    iban = _find_valid_iban(text)
    if iban:
        out.iban = iban
        out.source_by_field["iban"] = TransferFieldSource.PDF_TEXT
    bic = _find_valid_bic(text)
    if bic:
        out.bic = bic
        out.source_by_field["bic"] = TransferFieldSource.PDF_TEXT
    amount = _extract_amount_from_text(text)
    if amount is not None:
        out.amount = amount
        out.source_by_field["amount"] = TransferFieldSource.PDF_TEXT
    invoice_number = _extract_invoice_number(text)
    if invoice_number:
        out.invoice_number = invoice_number
        out.source_by_field["invoice_number"] = TransferFieldSource.PDF_TEXT
    remittance = _extract_remittance(text)
    if remittance:
        out.remittance_text = remittance
        out.source_by_field["remittance_text"] = TransferFieldSource.PDF_TEXT
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        out.recipient = lines[0][:70]
        out.source_by_field["recipient"] = TransferFieldSource.PDF_TEXT
    if not out.remittance_text and out.invoice_number:
        out.remittance_text = out.invoice_number
        out.source_by_field["remittance_text"] = TransferFieldSource.PDF_TEXT
    return out


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    pypdf_parts: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages[:3]:
            content = page.extract_text() or ""
            if content.strip():
                pypdf_parts.append(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF text extraction failed: %s", exc)
    pypdf_text = "\n".join(pypdf_parts).strip()

    if fitz is None:
        return pypdf_text

    fitz_parts: list[str] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            for page_idx in range(min(3, len(doc))):
                content = doc.load_page(page_idx).get_text("text") or ""
                if content.strip():
                    fitz_parts.append(content)
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("PyMuPDF text extraction failed: %s", exc)
    fitz_text = "\n".join(fitz_parts).strip()

    if _find_valid_iban(fitz_text) and not _find_valid_iban(pypdf_text):
        return fitz_text
    return fitz_text if len(fitz_text) > len(pypdf_text) else pypdf_text


def _normalize_epc_payload(value: str) -> str:
    return str(value or "").strip().replace("\r\n", "\n").replace("\r", "\n")


def _extract_existing_epc_payload(pdf_bytes: bytes) -> str:
    """Try to detect a QR code from first PDF pages and return EPC payload text."""
    if not pdf_bytes or cv2 is None or fitz is None or np is None:
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""
    try:
        detector = cv2.QRCodeDetector()
        for page_idx in range(min(2, len(doc))):
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(dpi=220, alpha=False)
            channels = int(getattr(pix, "n", 3) or 3)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, channels)
            if channels >= 3:
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            decoded_single, _points, _ = detector.detectAndDecode(image)
            single_payload = _normalize_epc_payload(decoded_single)
            if single_payload.startswith("BCD\n"):
                return single_payload

            ok_multi, decoded_list, _points_multi, _ = detector.detectAndDecodeMulti(image)
            if ok_multi and isinstance(decoded_list, (list, tuple)):
                for candidate in decoded_list:
                    text = _normalize_epc_payload(str(candidate or ""))
                    if text.startswith("BCD\n"):
                        return text
    except Exception as exc:  # noqa: BLE001
        logger.debug("Existing QR detection failed: %s", exc)
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass
    return ""


def _extract_payment_from_epc_payload(payload: str) -> TransferPaymentData:
    text = str(payload or "").strip()
    if not text.startswith("BCD"):
        return TransferPaymentData()

    lines = [line.strip() for line in text.splitlines()]
    # EPC SCT payload uses fixed positional lines. We parse only relevant fields.
    bic = lines[4] if len(lines) > 4 else ""
    recipient = lines[5] if len(lines) > 5 else ""
    iban = lines[6] if len(lines) > 6 else ""
    amount_line = lines[7] if len(lines) > 7 else ""
    remittance_ref = lines[9] if len(lines) > 9 else ""
    remittance_text = lines[10] if len(lines) > 10 else ""

    amount: Decimal | None = None
    if amount_line.upper().startswith("EUR"):
        amount = _parse_amount(amount_line[3:])
    else:
        amount = _parse_amount(amount_line)

    remittance = remittance_text or remittance_ref
    out = TransferPaymentData(
        recipient=recipient,
        iban=_normalize_iban(iban),
        bic=bic.upper(),
        amount=amount,
        remittance_text=remittance,
        source_by_field={
            "recipient": TransferFieldSource.PDF_EXISTING_QR,
            "iban": TransferFieldSource.PDF_EXISTING_QR,
            "bic": TransferFieldSource.PDF_EXISTING_QR,
            "amount": TransferFieldSource.PDF_EXISTING_QR,
            "remittance_text": TransferFieldSource.PDF_EXISTING_QR,
        },
    )
    if remittance_ref:
        out.invoice_number = remittance_ref
        out.source_by_field["invoice_number"] = TransferFieldSource.PDF_EXISTING_QR
    return out


def _openai_fallback(*, api_key: str, context_text: str) -> dict[str, Any]:
    prompt = (
        "Extrahiere Zahlungsdaten als JSON mit Schluesseln recipient, iban, bic, amount, remittance_text, invoice_number. "
        "Nur JSON ohne Erklaerung.\n\n"
        f"Kontext:\n{context_text[:10000]}"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": "gpt-4.1-mini",
        "input": prompt,
        "max_output_tokens": 300,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()

    raw = str(payload.get("output_text") or "").strip()
    if not raw and isinstance(payload.get("output"), list):
        for item in payload["output"]:
            if not isinstance(item, dict):
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    raw = block["text"].strip()
                    if raw:
                        break
            if raw:
                break
    if not raw:
        return {}
    raw = _strip_json_fence(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _strip_json_fence(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text.strip()


def _can_prefer(base: TransferPaymentData, field: str, prefer_patch_fields: set[str]) -> bool:
    return (
        field in prefer_patch_fields
        and base.source_by_field.get(field) != TransferFieldSource.PDF_EXISTING_QR
    )


def _merge_payment(
    base: TransferPaymentData,
    patch: TransferPaymentData,
    *,
    prefer_patch_fields: set[str] | None = None,
) -> TransferPaymentData:
    prefer_patch_fields = prefer_patch_fields or set()
    if patch.recipient and (not base.recipient or _can_prefer(base, "recipient", prefer_patch_fields)):
        base.recipient = patch.recipient
        base.source_by_field["recipient"] = patch.source_by_field.get("recipient", TransferFieldSource.UNKNOWN)
    if patch.iban and (not base.iban or _can_prefer(base, "iban", prefer_patch_fields)):
        base.iban = patch.iban
        base.source_by_field["iban"] = patch.source_by_field.get("iban", TransferFieldSource.UNKNOWN)
    if patch.bic and (not base.bic or _can_prefer(base, "bic", prefer_patch_fields)):
        base.bic = patch.bic
        base.source_by_field["bic"] = patch.source_by_field.get("bic", TransferFieldSource.UNKNOWN)
    if patch.amount is not None and (base.amount is None or _can_prefer(base, "amount", prefer_patch_fields)):
        base.amount = patch.amount
        base.source_by_field["amount"] = patch.source_by_field.get("amount", TransferFieldSource.UNKNOWN)
    if patch.remittance_text and (
        not base.remittance_text or _can_prefer(base, "remittance_text", prefer_patch_fields)
    ):
        base.remittance_text = patch.remittance_text
        base.source_by_field["remittance_text"] = patch.source_by_field.get("remittance_text", TransferFieldSource.UNKNOWN)
    if patch.invoice_number and (
        not base.invoice_number or _can_prefer(base, "invoice_number", prefer_patch_fields)
    ):
        base.invoice_number = patch.invoice_number
        base.source_by_field["invoice_number"] = patch.source_by_field.get("invoice_number", TransferFieldSource.UNKNOWN)
    return base


def extract_payment_data_from_sources(
    *,
    mail_text: str = "",
    thread_text: str = "",
    pdf_bytes: bytes | None = None,
    filename_hint: str = "",
    use_openai_fallback: bool = True,
    openai_api_key: str = "",
) -> TransferPaymentData:
    del filename_hint
    result = TransferPaymentData()

    pdf_text = _extract_pdf_text(pdf_bytes or b"") if pdf_bytes else ""
    if pdf_bytes:
        existing_epc_payload = _extract_existing_epc_payload(pdf_bytes)
        if existing_epc_payload:
            result = _merge_payment(result, _extract_payment_from_epc_payload(existing_epc_payload))
    result = _merge_payment(result, _extract_from_text(pdf_text))
    if not result.iban or result.amount is None:
        thread_extracted = _extract_from_text(f"{mail_text}\n{thread_text}")
        for field in list(thread_extracted.source_by_field):
            thread_extracted.source_by_field[field] = TransferFieldSource.THREAD
        result = _merge_payment(result, thread_extracted)

    needs_openai = (
        not result.recipient
        or not result.iban
        or result.amount is None
        or not result.remittance_text
        or result.source_by_field.get("recipient")
        in {TransferFieldSource.PDF_TEXT, TransferFieldSource.THREAD, TransferFieldSource.MAIL}
    )
    if use_openai_fallback and openai_api_key and needs_openai:
        try:
            ai_payload = _openai_fallback(
                api_key=openai_api_key,
                context_text=f"MAIL\n{mail_text}\n\nTHREAD\n{thread_text}\n\nPDF\n{pdf_text}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI payment extraction fallback failed: %s", exc)
            ai_payload = {}
        if ai_payload:
            ai_iban = _find_valid_iban(str(ai_payload.get("iban") or ""))
            ai_bic = _normalize_valid_bic(str(ai_payload.get("bic") or ""))
            ai_amount = _parse_amount(str(ai_payload.get("amount") or ""))
            source_by_field: dict[str, TransferFieldSource] = {}
            for key, value in {
                "recipient": ai_payload.get("recipient"),
                "iban": ai_iban,
                "bic": ai_bic,
                "amount": ai_amount,
                "remittance_text": ai_payload.get("remittance_text"),
                "invoice_number": ai_payload.get("invoice_number"),
            }.items():
                if value:
                    source_by_field[key] = TransferFieldSource.OPENAI
            ai_payment = TransferPaymentData(
                recipient=str(ai_payload.get("recipient") or "").strip(),
                iban=ai_iban,
                bic=ai_bic,
                amount=ai_amount,
                remittance_text=str(ai_payload.get("remittance_text") or "").strip(),
                invoice_number=str(ai_payload.get("invoice_number") or "").strip(),
                source_by_field=source_by_field,
            )
            result = _merge_payment(
                result,
                ai_payment,
                prefer_patch_fields={
                    "recipient",
                    "iban",
                    "bic",
                    "amount",
                    "remittance_text",
                    "invoice_number",
                },
            )

    if result.remittance_text == "" and result.invoice_number:
        result.remittance_text = result.invoice_number
        result.source_by_field.setdefault("remittance_text", TransferFieldSource.UNKNOWN)
    _prefer_invoice_number_for_remittance(result)
    return result


def create_epc_qr_from_payment_data(
    payment: TransferPaymentData,
    *,
    output_dir: Path,
    filename_hint: str = "",
) -> Path:
    _validate_payment(payment)
    safe_hint = re.sub(r"[^a-zA-Z0-9_-]", "_", filename_hint).strip("_") or "transfer"
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"epc_qr_{safe_hint}_{ts}.png"

    invoice_number = str(payment.invoice_number or "").strip()
    remittance = invoice_number or str(payment.remittance_text or "").strip()
    structured_reference = remittance if _is_structured_epc_reference(remittance) else None
    unstructured_text = None if structured_reference else (remittance or None)

    qr = helpers.make_epc_qr(
        name=payment.recipient,
        iban=payment.iban,
        amount=payment.amount,
        text=unstructured_text,
        reference=structured_reference,
        bic=(payment.bic or None),
    )
    qr.save(output_path, kind="png", scale=10)
    return output_path


def payment_to_json_dict(payment: TransferPaymentData) -> dict[str, Any]:
    payload = asdict(payment)
    if payment.amount is not None:
        payload["amount"] = str(payment.amount)
    payload["source_by_field"] = {k: str(v.value) for k, v in payment.source_by_field.items()}
    return payload
