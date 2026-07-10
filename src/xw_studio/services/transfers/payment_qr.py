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

from xw_studio.services.transfers.models import TransferFieldSource, TransferPaymentData

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))(?!\d)")
_IBAN_RE = re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9 ]{10,40}\b")
_BIC_RE = re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
_INVOICE_RE = re.compile(
    r"\b(?:RE|RG|INV)(?:[-\s]*\d[A-Z0-9-]{2,}|[-\s]+[A-Z0-9-]{2,}\d[A-Z0-9-]*)\b",
    re.IGNORECASE,
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


def _extract_from_text(text: str) -> TransferPaymentData:
    out = TransferPaymentData()
    if not text:
        return out
    iban_match = _IBAN_RE.search(text.upper())
    if iban_match:
        out.iban = _normalize_iban(iban_match.group(0))
        out.source_by_field["iban"] = TransferFieldSource.PDF_TEXT
    bic_match = _BIC_RE.search(text.upper())
    if bic_match:
        out.bic = bic_match.group(0).strip().upper()
        out.source_by_field["bic"] = TransferFieldSource.PDF_TEXT
    amount_match = _AMOUNT_RE.search(text)
    if amount_match:
        amount = _parse_amount(amount_match.group(1))
        if amount is not None:
            out.amount = amount
            out.source_by_field["amount"] = TransferFieldSource.PDF_TEXT
    invoice_match = _INVOICE_RE.search(text)
    if invoice_match:
        out.invoice_number = invoice_match.group(0).strip()
        out.source_by_field["invoice_number"] = TransferFieldSource.PDF_TEXT
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        out.recipient = lines[0][:70]
        out.source_by_field["recipient"] = TransferFieldSource.PDF_TEXT
    if out.invoice_number:
        out.remittance_text = out.invoice_number
        out.source_by_field["remittance_text"] = TransferFieldSource.PDF_TEXT
    return out


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    parts: list[str] = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages[:3]:
            content = page.extract_text() or ""
            if content.strip():
                parts.append(content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF text extraction failed: %s", exc)
    return "\n".join(parts).strip()


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
            if isinstance(decoded_single, str) and decoded_single.strip().startswith("BCD\n"):
                return decoded_single.strip()

            ok_multi, decoded_list, _points_multi, _ = detector.detectAndDecodeMulti(image)
            if ok_multi and isinstance(decoded_list, (list, tuple)):
                for candidate in decoded_list:
                    text = str(candidate or "").strip()
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
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _merge_payment(base: TransferPaymentData, patch: TransferPaymentData) -> TransferPaymentData:
    if patch.recipient and not base.recipient:
        base.recipient = patch.recipient
        base.source_by_field["recipient"] = patch.source_by_field.get("recipient", TransferFieldSource.UNKNOWN)
    if patch.iban and not base.iban:
        base.iban = patch.iban
        base.source_by_field["iban"] = patch.source_by_field.get("iban", TransferFieldSource.UNKNOWN)
    if patch.bic and not base.bic:
        base.bic = patch.bic
        base.source_by_field["bic"] = patch.source_by_field.get("bic", TransferFieldSource.UNKNOWN)
    if patch.amount is not None and base.amount is None:
        base.amount = patch.amount
        base.source_by_field["amount"] = patch.source_by_field.get("amount", TransferFieldSource.UNKNOWN)
    if patch.remittance_text and not base.remittance_text:
        base.remittance_text = patch.remittance_text
        base.source_by_field["remittance_text"] = patch.source_by_field.get("remittance_text", TransferFieldSource.UNKNOWN)
    if patch.invoice_number and not base.invoice_number:
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

    if use_openai_fallback and openai_api_key and (not result.iban or result.amount is None):
        try:
            ai_payload = _openai_fallback(
                api_key=openai_api_key,
                context_text=f"MAIL\n{mail_text}\n\nTHREAD\n{thread_text}\n\nPDF\n{pdf_text}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAI payment extraction fallback failed: %s", exc)
            ai_payload = {}
        if ai_payload:
            ai_amount = _parse_amount(str(ai_payload.get("amount") or ""))
            ai_payment = TransferPaymentData(
                recipient=str(ai_payload.get("recipient") or "").strip(),
                iban=str(ai_payload.get("iban") or "").strip(),
                bic=str(ai_payload.get("bic") or "").strip(),
                amount=ai_amount,
                remittance_text=str(ai_payload.get("remittance_text") or "").strip(),
                invoice_number=str(ai_payload.get("invoice_number") or "").strip(),
                source_by_field={
                    "recipient": TransferFieldSource.OPENAI,
                    "iban": TransferFieldSource.OPENAI,
                    "bic": TransferFieldSource.OPENAI,
                    "amount": TransferFieldSource.OPENAI,
                    "remittance_text": TransferFieldSource.OPENAI,
                    "invoice_number": TransferFieldSource.OPENAI,
                },
            )
            result = _merge_payment(result, ai_payment)

    if result.remittance_text == "" and result.invoice_number:
        result.remittance_text = result.invoice_number
        result.source_by_field.setdefault("remittance_text", TransferFieldSource.UNKNOWN)
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

    qr = helpers.make_epc_qr(
        name=payment.recipient,
        iban=payment.iban,
        amount=payment.amount,
        text=(payment.remittance_text or None),
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
