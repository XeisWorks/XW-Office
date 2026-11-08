from xw_office.ui.modules.rechnungen.open_invoice_overview import PrintProductAggregate, plan_open_print_products


def test_pod_stock_is_consumed_before_batch_print_and_next_demand_uses_remainder() -> None:
    products = [
        PrintProductAggregate("POD-1", "Titel", "", 3),
        PrintProductAggregate("POD-1", "Titel", "", 1),
    ]
    planned = plan_open_print_products(products, stock_by_sku={"POD-1": 2}, article_kind_by_sku={"POD-1": "pod"})
    assert planned[0].from_stock == 2
    assert planned[0].quantity == 3
    assert planned[1].from_stock == 1
    assert planned[1].quantity == 0


def test_external_print_shortage_is_replenishment_without_local_print() -> None:
    planned = plan_open_print_products(
        [PrintProductAggregate("EXT-1", "Druckerei", "", 2)],
        stock_by_sku={"EXT-1": 1},
        article_kind_by_sku={"EXT-1": "external_print"},
    )[0]
    assert planned.from_stock == 1
    assert planned.quantity == 0
    assert planned.disposition == "nachbestellen"
