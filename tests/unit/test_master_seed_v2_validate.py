"""Tests for the Master Seed V2 hard-invariant validator."""
from __future__ import annotations

from pathlib import Path

from xw_office.services.product_hub.master_seed_v2_validate import (
    load_master_seed_v2_rows,
    validate_master_seed_v2_rows,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MASTER_SEED_CSV = _REPO_ROOT / "docs" / "producthub_master-seed" / "XW_Product_Hub_Master_Seed_2026-09-17.csv"

_BASE_COLUMNS = [
    "sku", "canonical_sku", "product_group_id", "canonical_variant", "variant_role",
    "record_state", "brand", "category_primary", "title_full", "title_short", "code_short",
]


def _row(**overrides: str) -> dict[str, str]:
    base = {col: "" for col in _BASE_COLUMNS}
    base.update(overrides)
    return base


# -- against the real shipped CSV ----------------------------------------------------


def test_real_master_seed_v2_csv_has_915_unique_skus_and_no_blocking_issues() -> None:
    rows = load_master_seed_v2_rows(_MASTER_SEED_CSV)
    report = validate_master_seed_v2_rows(rows)

    assert report.total_rows == 915
    assert report.unique_skus == 915
    assert report.is_valid, report.blocking_issues


def test_real_master_seed_v2_csv_has_exactly_the_one_known_review_exemption() -> None:
    rows = load_master_seed_v2_rows(_MASTER_SEED_CSV)
    report = validate_master_seed_v2_rows(rows)

    assert len(report.known_review_issues) == 1
    issue = report.known_review_issues[0]
    assert issue.sku == "XW-017"
    assert issue.rule == "forbidden_word"
    assert issue.field == "code_short"


# -- synthetic edge cases, independent of the CSV's current content ------------------


def test_duplicate_sku_is_blocking() -> None:
    rows = [_row(sku="XW-1", title_full="A"), _row(sku="XW-1", title_full="B")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "duplicate_sku" for i in report.blocking_issues)


def test_three_digit_xw4_sku_is_blocking() -> None:
    rows = [_row(sku="XW-400", title_full="Legacy", brand="Blechhaufn")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "three_digit_xw4_canonical_sku" for i in report.blocking_issues)


def test_four_digit_xw4_sku_is_not_flagged() -> None:
    rows = [_row(sku="XW-4000", title_full="Kanonisch", brand="Blechhaufn")]
    report = validate_master_seed_v2_rows(rows)
    assert not any(i.rule == "three_digit_xw4_canonical_sku" for i in report.blocking_issues)


def test_forbidden_word_on_non_review_row_is_blocking() -> None:
    rows = [_row(sku="XW-9001", title_full="Zusatzstimme Horn", record_state="ACTIVE")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "forbidden_word" for i in report.blocking_issues)
    assert report.known_review_issues == []


def test_forbidden_word_on_review_row_is_reported_not_blocking() -> None:
    rows = [_row(sku="XW-9002", title_full="ok", code_short="ZUSATZSTIMME_X", record_state="REVIEW")]
    report = validate_master_seed_v2_rows(rows)
    assert report.blocking_issues == []
    assert any(i.rule == "forbidden_word" for i in report.known_review_issues)


def test_band_word_is_forbidden_case_insensitive() -> None:
    rows = [_row(sku="XW-9003", title_full="Volksmusik - band 2", record_state="ACTIVE")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "forbidden_word" for i in report.blocking_issues)


def test_brand_mismatch_for_40_series_is_blocking() -> None:
    rows = [_row(sku="XW-4001", title_full="X", brand="XeisWorks")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "brand_mismatch" for i in report.blocking_issues)


def test_brand_mismatch_for_45_series_is_blocking() -> None:
    rows = [_row(sku="XW-4501", title_full="X", brand="Blechhaufn")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "brand_mismatch" for i in report.blocking_issues)


def test_brand_correct_for_1_2_3_series_passes() -> None:
    rows = [
        _row(sku="XW-101", title_full="X", brand="XeisWorks"),
        _row(sku="XW-201", title_full="X", brand="XeisWorks"),
        _row(sku="XW-301", title_full="X", brand="XeisWorks"),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert not any(i.rule == "brand_mismatch" for i in report.blocking_issues)


def test_zusatzstimme_category_required_for_dotted_1xx_sku() -> None:
    rows = [_row(sku="XW-102.5", title_full="X", brand="XeisWorks", category_primary="Noten")]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "zusatzstimme_category_mismatch" for i in report.blocking_issues)


def test_bare_1xx_sku_without_dot_suffix_is_not_zusatzstimme() -> None:
    rows = [_row(sku="XW-102", title_full="X", brand="XeisWorks", category_primary="Heft")]
    report = validate_master_seed_v2_rows(rows)
    assert not any(i.rule == "zusatzstimme_category_mismatch" for i in report.blocking_issues)


def test_group_needs_exactly_one_canonical_variant() -> None:
    rows = [
        _row(sku="XW-A", product_group_id="g1", canonical_variant="false"),
        _row(sku="XW-B", product_group_id="g1", canonical_variant="false"),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "canonical_variant_count" for i in report.blocking_issues)


def test_group_with_two_canonical_variants_is_blocking() -> None:
    rows = [
        _row(sku="XW-A", product_group_id="g1", canonical_variant="true", title_full="X"),
        _row(sku="XW-B", product_group_id="g1", canonical_variant="true", title_full="X"),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "canonical_variant_count" for i in report.blocking_issues)


def test_pure_format_variant_must_match_canonical_title() -> None:
    rows = [
        _row(sku="XW-A", product_group_id="g1", canonical_variant="true", variant_role="CANONICAL", title_full="Basis", title_short="Basis"),
        _row(sku="XW-A-D", product_group_id="g1", canonical_variant="false", variant_role="FORMAT_VARIANT", title_full="Anders", title_short="Anders"),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert any(i.rule == "format_variant_title_mismatch" for i in report.blocking_issues)


def test_matching_format_variant_title_passes() -> None:
    rows = [
        _row(sku="XW-A", product_group_id="g1", canonical_variant="true", variant_role="CANONICAL", title_full="Basis", title_short="Basis"),
        _row(sku="XW-A-D", product_group_id="g1", canonical_variant="false", variant_role="FORMAT_VARIANT", title_full="Basis", title_short="Basis", code_short="BASIS_D"),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert not any(i.rule == "format_variant_title_mismatch" for i in report.blocking_issues)


def test_composite_format_and_scoring_variant_is_exempt_from_title_equality() -> None:
    """A FORMAT_VARIANT|SCORING_VARIANT row (e.g. a digital "Register-4er" edition) is a
    different arrangement, not merely a different format of the same content — its
    title is expected to differ. Confirmed against the real V2 seed (XW-301/XW-302)."""
    rows = [
        _row(sku="XW-A", product_group_id="g1", canonical_variant="true", variant_role="CANONICAL", title_full="Basis"),
        _row(
            sku="XW-A-R4",
            product_group_id="g1",
            canonical_variant="false",
            variant_role="FORMAT_VARIANT|SCORING_VARIANT",
            title_full="Basis [Register-4er]",
        ),
    ]
    report = validate_master_seed_v2_rows(rows)
    assert not any(i.rule == "format_variant_title_mismatch" for i in report.blocking_issues)
