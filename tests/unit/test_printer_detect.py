"""Tests for printer traffic-light evaluation."""

from xw_office.core.printer_detect import PrinterInfo, evaluate_printer_status
from xw_office.core.types import PrinterStatus


def test_no_config_and_no_available_is_red() -> None:
    assert evaluate_printer_status([], []) == PrinterStatus.RED


def test_no_config_but_available_is_green() -> None:
    available = [PrinterInfo(name="HP Laser", is_default=True)]
    assert evaluate_printer_status(available, []) == PrinterStatus.GREEN


def test_configured_but_none_matched_is_red() -> None:
    available = [PrinterInfo(name="HP Laser")]
    assert evaluate_printer_status(available, ["Canon Office"]) == PrinterStatus.RED


def test_partial_match_is_yellow() -> None:
    available = [PrinterInfo(name="HP Laser")]
    assert evaluate_printer_status(available, ["HP Laser", "Canon Office"]) == PrinterStatus.YELLOW


def test_all_configured_matched_is_green() -> None:
    available = [PrinterInfo(name="HP Laser"), PrinterInfo(name="Canon Office")]
    assert evaluate_printer_status(available, ["Canon Office", "HP Laser"]) == PrinterStatus.GREEN
