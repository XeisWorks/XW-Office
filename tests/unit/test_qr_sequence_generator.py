from __future__ import annotations

import pytest

from xw_office.services.qr_codes.models import NumericSequenceSpec, QrConfigurationError
from xw_office.services.qr_codes.presets import generate_numbers


def test_generate_numbers_pads_single_digits_but_not_longer_numbers() -> None:
    numbers = generate_numbers(NumericSequenceSpec(start=1, end=111, step=1, minimum_width=2))

    displayed = [d for _raw, d in numbers]
    assert displayed[0] == "01"
    assert displayed[8] == "09"
    assert displayed[9] == "10"
    assert displayed[-1] == "111"
    assert len(numbers) == 111


def test_generate_numbers_applies_suffix() -> None:
    numbers = generate_numbers(NumericSequenceSpec(start=4, end=24, step=4, minimum_width=2, number_suffix="d"))

    assert [d for _raw, d in numbers] == ["04d", "08d", "12d", "16d", "20d", "24d"]


def test_generate_numbers_returns_raw_int_without_suffix() -> None:
    numbers = generate_numbers(NumericSequenceSpec(start=1, end=3, step=1, minimum_width=2, number_suffix="d"))

    assert [raw for raw, _d in numbers] == [1, 2, 3]


def test_generate_numbers_rejects_zero_step() -> None:
    with pytest.raises(QrConfigurationError):
        generate_numbers(NumericSequenceSpec(start=1, end=10, step=0))


def test_generate_numbers_rejects_end_before_start() -> None:
    with pytest.raises(QrConfigurationError):
        generate_numbers(NumericSequenceSpec(start=10, end=1, step=1))
