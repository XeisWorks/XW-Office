from decimal import Decimal

import pytest

from xw_office.services.finanzonline.tax_followup_models import (
    TaxPayment,
    build_transfer_body,
    uva_payment,
)


def test_uva_negative_and_zero_never_become_payment() -> None:
    kwargs = {"period": "09/2026", "calculation_hash_value": "abc", "recipient": "BMF", "iban": "AT00", "bic": "", "remittance": "UVA", "due_date": "2026-11-15"}
    assert uva_payment(**kwargs, zahlbetrag="0,00") is None
    assert uva_payment(**kwargs, zahlbetrag="-12,34") is None


def test_transfer_contract_has_stable_labels_and_key() -> None:
    payment = TaxPayment("uva", "09/2026", "abc", "BMF", "AT611904300234573201", "", Decimal("12.34"), "UVA-09/2026", "2026-11-15")
    body = build_transfer_body(payment)
    assert "XW-Payment-Version: 1" in body
    assert "XW-Payment-Key: tax:uva:09/2026:abc" in body
    assert "Empfänger: BMF" in body


def test_payment_rejects_non_eur_or_non_positive() -> None:
    with pytest.raises(ValueError):
        TaxPayment("uva", "09/2026", "abc", "BMF", "AT611904300234573201", "", Decimal(0), "UVA", "2026-11-15")


def test_payment_rejects_invalid_bank_details() -> None:
    with pytest.raises(ValueError, match="IBAN"):
        TaxPayment("uva", "09/2026", "abc", "BMF", "AT123", "", Decimal(1), "UVA", "2026-11-15")
