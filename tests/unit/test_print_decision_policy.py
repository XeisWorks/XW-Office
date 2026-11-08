from xw_office.services.products.catalog import PrintRule, Product, StockStatus
from xw_office.services.products.print_decision import PieceBlock


def _piece(kind: str, on_hand: int, needed: int = 1) -> PieceBlock:
    product = Product(
        id="test", sku="SKU-1", name="Titel", article_kind=kind,
        print_rule=PrintRule(reprint_batch_qty=3),
    )
    return PieceBlock(
        sku="SKU-1", name="Titel", qty_needed=needed, product=product,
        stock_status=StockStatus("SKU-1", "Titel", False, on_hand, 5, 3),
    )


def test_pod_uses_stock_before_print_and_prints_three_on_shortage() -> None:
    assert _piece("pod", 2, 1).print_qty == 0
    assert _piece("pod", 0, 1).print_qty == 3
    assert _piece("pod", 0, 1).needs_print is True


def test_external_print_shortage_is_replenishment_not_local_print() -> None:
    piece = _piece("external_print", 0, 1)
    assert piece.needs_print is False
    assert piece.needs_replenishment is True
    assert piece.print_qty == 0
    assert "Nachbestellen" in piece.stock_label
