"""Tests for the centralized B2B/B2C reference classification rules."""
from __future__ import annotations

from xw_studio.core.config import AppConfig, SkuRulesSection
from xw_studio.services.products.classification_rules import (
    ReferenceClass,
    ReferenceClassifier,
    classify_reference,
)


def test_classify_reference_b2b_prefix() -> None:
    result = classify_reference("100234", b2b_prefixes=["1"], b2c_prefixes=["2"])
    assert result is ReferenceClass.B2B


def test_classify_reference_b2c_prefix() -> None:
    result = classify_reference("200234", b2b_prefixes=["1"], b2c_prefixes=["2"])
    assert result is ReferenceClass.B2C


def test_classify_reference_unknown_prefix() -> None:
    result = classify_reference("900234", b2b_prefixes=["1"], b2c_prefixes=["2"])
    assert result is ReferenceClass.UNKNOWN


def test_classify_reference_empty_is_unknown() -> None:
    assert classify_reference("", b2b_prefixes=["1"], b2c_prefixes=["2"]) is ReferenceClass.UNKNOWN
    assert classify_reference("   ", b2b_prefixes=["1"], b2c_prefixes=["2"]) is ReferenceClass.UNKNOWN


def test_classify_reference_b2b_checked_before_b2c_on_overlap() -> None:
    # If prefixes were ever misconfigured to overlap, B2B must win deterministically.
    result = classify_reference("12345", b2b_prefixes=["12"], b2c_prefixes=["1"])
    assert result is ReferenceClass.B2B


def test_reference_classifier_from_config_uses_sku_rules_defaults() -> None:
    classifier = ReferenceClassifier.from_config(AppConfig().sku_rules)
    assert classifier.classify("100234") is ReferenceClass.B2B
    assert classifier.classify("200234") is ReferenceClass.B2C


def test_reference_classifier_respects_custom_config() -> None:
    config = SkuRulesSection(b2b_reference_prefixes=["B"], b2c_reference_prefixes=["C"])
    classifier = ReferenceClassifier.from_config(config)
    assert classifier.classify("B-1001") is ReferenceClass.B2B
    assert classifier.classify("C-1001") is ReferenceClass.B2C
    assert classifier.classify("X-1001") is ReferenceClass.UNKNOWN
