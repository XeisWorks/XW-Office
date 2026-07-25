"""B2B direct-bank-transfer invoice reference extraction.

Legacy ``b2b-bank-transfer.py`` matched direct SEPA transfers (no Wix
order involved, e.g. a band paying an invoice straight from its bank
account) by scanning the transaction purpose text for a 6-digit invoice
number carrying the invoice's issue year as its first two digits, e.g.
"261234" for invoice ``RE-261234`` issued in 2026. This is structurally
distinct from the 5-digit Wix order number the rest of clearing matches
on (see ``_ORDER_NUMBER`` in :mod:`xw_studio.services.clearing.service`),
so it needs its own extraction rather than a shared regex.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

_SIX_DIGIT_RUN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def extract_b2b_invoice_numbers(purpose: str, *, year_prefixes: Sequence[str]) -> tuple[str, ...]:
    """Return distinct ``RE-NNNNNN`` invoice references found in *purpose*.

    Only 6-digit runs whose first two digits are in *year_prefixes* (the
    invoice's issue year) are accepted — this rejects unrelated 6-digit
    numbers (phone numbers, partial IBAN fragments, ...) that happen to
    appear in a bank transfer's free-text purpose line. A single transfer
    may reference more than one invoice; all distinct matches are returned
    in the order they appear.
    """
    allowed_years = {str(year).strip() for year in year_prefixes if str(year).strip()}
    if not allowed_years:
        return ()
    seen: list[str] = []
    for match in _SIX_DIGIT_RUN.finditer(purpose or ""):
        digits = match.group(1)
        if digits[:2] not in allowed_years:
            continue
        reference = f"RE-{digits}"
        if reference not in seen:
            seen.append(reference)
    return tuple(seen)
