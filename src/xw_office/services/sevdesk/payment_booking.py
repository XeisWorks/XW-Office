from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

import httpx


CENT = Decimal("0.01")


def normalize_booking_amount(amount: object) -> float:
    """Normalize sevDesk booking amounts to two decimal places."""
    try:
        return float(Decimal(str(amount or "0")).quantize(CENT, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0.0


def response_payload(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def raise_on_error_envelope(payload: dict[str, Any], context: str) -> None:
    """sevDesk can return HTTP 200 with an error object inside the JSON body."""
    if not payload.get("error"):
        return
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error
    else:
        message = error
    raise RuntimeError(f"{context}: {message}")


def first_object(payload: object) -> dict[str, Any]:
    if isinstance(payload, dict):
        objects = payload.get("objects", payload)
        if isinstance(objects, list):
            return next((item for item in objects if isinstance(item, dict)), {})
        if isinstance(objects, dict):
            return objects
        return payload
    if isinstance(payload, list):
        return next((item for item in payload if isinstance(item, dict)), {})
    return {}


def is_paid_invoice_object(invoice: dict[str, Any]) -> bool:
    for key in ("paid", "isPaid"):
        value = invoice.get(key)
        if isinstance(value, bool):
            return value
        if str(value).strip().casefold() in {"true", "1", "yes"}:
            return True
    status_raw = str(invoice.get("status") or invoice.get("paymentStatus") or "").strip().casefold()
    if status_raw in {"paid", "bezahlt", "1000"}:
        return True
    for key in ("sumOutstanding", "openAmount", "amountOutstanding"):
        value = invoice.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            if float(str(value).replace(",", ".")) <= 0.0001:
                return True
        except (TypeError, ValueError):
            continue
    return False


def book_amount_payload(
    *,
    amount: object,
    booking_date: int,
    check_account_id: int,
    transaction_id: int,
) -> dict[str, Any]:
    return {
        "amount": normalize_booking_amount(amount),
        "date": int(booking_date),
        "type": "FULL_PAYMENT",
        "checkAccount": {"id": int(check_account_id), "objectName": "CheckAccount"},
        "checkAccountTransaction": {
            "id": int(transaction_id),
            "objectName": "CheckAccountTransaction",
        },
        "createFeed": False,
    }
