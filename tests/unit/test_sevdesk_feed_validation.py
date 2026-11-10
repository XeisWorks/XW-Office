from __future__ import annotations

import pytest

from xw_office.services.product_hub.sevdesk_feed_validation import document_state, feed_quantity


@pytest.mark.parametrize("status", [200, 750, 1000, "200", "open", "open/due", "partially paid", "paid"])
def test_supported_final_sevdesk_statuses(status: object) -> None:
    assert document_state({"status": status}) == "final"


@pytest.mark.parametrize("status", [None, "", 50, 300, "unknown"])
def test_unknown_status_is_never_final(status: object) -> None:
    assert document_state({"status": status}) == "unknown"


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "bad", -1])
def test_quantity_requires_a_finite_non_negative_number(value: object) -> None:
    assert feed_quantity({"quantity": value}) is None


@pytest.mark.parametrize("value, expected", [(0, "0"), ("0.5", "0.5"), ("1.5", "1.5"), ("2.0", "2.0")])
def test_quantity_preserves_decimal_value(value: object, expected: str) -> None:
    quantity = feed_quantity({"quantity": value})
    assert quantity is not None
    assert str(quantity) == expected
