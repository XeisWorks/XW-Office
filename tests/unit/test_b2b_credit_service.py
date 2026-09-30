from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

from xw_office.core.config import B2bCreditSection
from xw_office.services.b2b_credit import B2bCreditService
from xw_office.services.sevdesk.invoice_client import InvoiceSummary


def _summary(*, invoice_id: str, net: str, gross: str, order: str, name: str) -> InvoiceSummary:
    return InvoiceSummary(
        id=invoice_id,
        invoiceNumber=f"RE-{invoice_id}",
        sumNet=net,
        sumGross=gross,
        order_reference=order,
        contact_name=name,
    )


def test_paid_b2c_is_not_blocked_and_unpaid_over_limit_is_blocked() -> None:
    wix = Mock()
    wix.resolve_order.side_effect = [
        {"id": "wix-paid", "paymentStatus": "PAID"},
        {"id": "wix-unpaid", "paymentStatus": "NOT_PAID"},
    ]
    service = B2bCreditService(B2bCreditSection(default_net_limit=1000), wix)

    holds = service.evaluate(
        [
            _summary(invoice_id="21415", net="2500", gross="3000", order="21415", name="B2C"),
            _summary(invoice_id="21405", net="2500", gross="3000", order="21405", name="Firma"),
        ]
    )

    assert [hold.order_reference for hold in holds] == ["21405"]
    assert holds[0].payment_status == "NOT_PAID"


def test_exact_limit_is_allowed_and_customer_override_is_used() -> None:
    wix = Mock()
    wix.resolve_order.return_value = {"id": "wix", "paymentStatus": "NOT_PAID"}
    settings = Mock()
    settings.get_value_json.return_value = '{"firma": "3000.00"}'
    service = B2bCreditService(B2bCreditSection(default_net_limit=1000), wix, settings)

    assert service.evaluate([_summary(invoice_id="1", net="3000", gross="3600", order="1", name="Firma")]) == []
    assert service.evaluate([_summary(invoice_id="2", net="3000.01", gross="3600", order="2", name="Firma")])[0].limit == Decimal("3000.00")


def test_installment_plan_rounding_and_due_dates() -> None:
    wix = Mock()
    service = B2bCreditService(B2bCreditSection(), wix)
    wix.resolve_order.return_value = {"id": "wix", "paymentStatus": "NOT_PAID"}
    hold = service.evaluate([_summary(invoice_id="1", net="2000", gross="119.99", order="1", name="Firma")])[0]

    plan = service.create_installment_plan(hold, accepted_on=date(2026, 9, 30))
    assert [row.amount_gross for row in plan.rows] == [Decimal("36.00"), Decimal("42.00"), Decimal("41.99")]
    assert plan.rows[0].due_date == date(2026, 10, 7)
    assert plan.rows[1].due_date == date(2026, 10, 21)
    assert plan.rows[2].due_date == date(2026, 11, 11)
