from __future__ import annotations

import pytest

from xw_office.services.product_hub.inventory_policy import (
    ArticleKind,
    StockAvailability,
    build_print_plan,
)


def test_pod_prints_three_when_one_copy_is_missing() -> None:
    plan = build_print_plan(
        article_kind=ArticleKind.POD,
        demand=1,
        availability=StockAvailability(on_hand=0, reserved=0),
    )

    assert plan.consume_from_stock == 0
    assert plan.shortage == 1
    assert plan.print_qty == 3
    assert plan.reason == "pod_batch"


def test_pod_uses_stock_before_printing_and_rounds_to_batches() -> None:
    plan = build_print_plan(
        article_kind="pod",
        demand=5,
        availability=StockAvailability(on_hand=2, reserved=0),
    )

    assert plan.consume_from_stock == 2
    assert plan.shortage == 3
    assert plan.print_qty == 3


def test_external_print_shortage_is_replenishment_not_local_print() -> None:
    plan = build_print_plan(
        article_kind=ArticleKind.EXTERNAL_PRINT,
        demand=4,
        availability=StockAvailability(on_hand=1, reserved=0),
    )

    assert plan.consume_from_stock == 1
    assert plan.print_qty == 0
    assert plan.shortage == 3
    assert plan.reason == "replenishment"


def test_reserved_stock_is_not_available_and_digital_has_no_print() -> None:
    plan = build_print_plan(
        article_kind=ArticleKind.DIGITAL,
        demand=4,
        availability=StockAvailability(on_hand=10, reserved=7),
    )

    assert plan.available_before == 3
    assert plan.consume_from_stock == 0
    assert plan.print_qty == 0
    assert plan.reason == "digital"


def test_negative_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        build_print_plan(
            article_kind="pod",
            demand=-1,
            availability=StockAvailability(on_hand=0, reserved=0),
        )
