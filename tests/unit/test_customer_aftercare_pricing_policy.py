"""Tests for CustomerAftercarePricingPolicy (spec §9 — Kulanz vs. normale Wix-B2B-Konditionen)."""
from __future__ import annotations

from xw_office.core.config import CustomerAftercareSection
from xw_office.services.customer_aftercare.pricing_policy import CustomerAftercarePricingPolicy


def _policy() -> CustomerAftercarePricingPolicy:
    return CustomerAftercarePricingPolicy(CustomerAftercareSection())


def test_courtesy_gives_exact_30_percent_product_discount() -> None:
    """PRICE-01."""
    result = _policy().resolve_product_discount(courtesy=True)
    assert result.percent == 30.0
    assert result.is_percentage is True
    assert result.source == "courtesy"


def test_courtesy_gives_exact_100_percent_shipping_discount() -> None:
    """PRICE-01."""
    result = _policy().resolve_shipping_discount(courtesy=True)
    assert result.percent == 100.0
    assert result.source == "courtesy"


def test_non_courtesy_passes_through_existing_wix_b2b_discount() -> None:
    """PRICE-02 / testmatrix #8: normale Wix-B2B-Rabatte gelten unveraendert."""
    result = _policy().resolve_product_discount(courtesy=False, order_context_discount_percent=15.0)
    assert result.percent == 15.0
    assert result.source == "wix_b2b_rules"


def test_non_courtesy_passes_through_existing_shipping_cost_when_none_given() -> None:
    """PRICE-02: no courtesy override -> normale Versandkosten (0% discount by default)."""
    result = _policy().resolve_shipping_discount(courtesy=False)
    assert result.percent == 0.0
    assert result.source == "existing_wix_shipping_logic"


def test_courtesy_percentages_are_config_driven_not_hardcoded() -> None:
    config = CustomerAftercareSection()
    custom = CustomerAftercareSection(
        courtesy=config.courtesy.__class__(
            default_enabled=True, product_discount_percent=42, shipping_discount_percent=77
        )
    )
    policy = CustomerAftercarePricingPolicy(custom)

    assert policy.resolve_product_discount(courtesy=True).percent == 42.0
    assert policy.resolve_shipping_discount(courtesy=True).percent == 77.0
