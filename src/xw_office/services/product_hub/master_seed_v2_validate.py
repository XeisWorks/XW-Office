"""Hard-invariant validator for the Master Seed V2 CSV (2026-09-17).

Runs *before* any DB import — these are the invariants the V2 README documents under
"Harte Validierungen vor Import". A violation here means the seed file itself is wrong
and must be fixed upstream; this module never repairs data, it only reports.

One documented exception: rows already in ``record_state == "REVIEW"`` are excluded
from the forbidden-word check's *blocking* list (they show up in
``known_review_issues`` instead). A row already flagged for human review is, by
definition, not yet trusted content — failing the whole import over a field that a
human is already going to look at would block 914 good rows over 1 already-known one.
As of the 2026-09-17 V2 seed this affects exactly one row (``XW-017``'s ``code_short``,
also listed in ``XW_Product_Hub_Review_Conflicts_V2_2026-09-17.csv``); the test suite
pins that fact down so a *new* review-exempted violation doesn't slip through silently.

Forbidden-word matching is plain case-insensitive substring search, not word-boundary
matching: ``code_short`` values are underscore-joined tokens (e.g.
``ZUSATZSTIMME_INDIVIDUELL_P``), where a ``\\b`` boundary never fires around
underscores. Checked against the actual V2 data, substring search finds exactly the one
real violation above and nothing else — see the test suite for the empirical check.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

_FORBIDDEN_WORDS = ("Zusatzstimme", "ZST", "ZS", "Band")
_TITLE_FIELDS = ("title_full", "title_short", "code_short")

#: XW-4xx with *exactly* three digits (legacy, pre-V2 form) — canonical V2 SKUs in the
#: 4000 range are always four digits (``XW-4000``..``XW-4999``, optionally dotted).
_THREE_DIGIT_XW4 = re.compile(r"^XW-4\d{2}(?!\d)")
#: XW-1xx.* / XW-2xx.* — only the *dotted* suffix rows are individual voice parts
#: ("Zusatzstimme"); the bare three-digit booklet SKU (e.g. ``XW-102``) is not.
_ZUSATZSTIMME_SKU = re.compile(r"^XW-[12]\d{2}\.")
_BRAND_45 = re.compile(r"^XW-45\d*")
_BRAND_40 = re.compile(r"^XW-40\d*")
_BRAND_123 = re.compile(r"^XW-[123]\d")

_BRAND_XEISWORKS = "XeisWorks"
_BRAND_BLECHHAUFN = "Blechhaufn"
_BRAND_MNOZIL = "Mnozil Brass"
_ZUSATZSTIMME_CATEGORY = "Zusatzstimme"


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class ValidationIssue:
    sku: str
    rule: str
    field: str
    detail: str


@dataclass
class MasterSeedV2ValidationReport:
    total_rows: int = 0
    unique_skus: int = 0
    blocking_issues: list[ValidationIssue] = field(default_factory=list)
    #: Violations on rows already flagged ``record_state == "REVIEW"`` — reported, not
    #: blocking. See module docstring.
    known_review_issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.blocking_issues


def load_master_seed_v2_rows(csv_path: str | Path) -> list[dict[str, str]]:
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_master_seed_v2_rows(rows: list[dict[str, str]]) -> MasterSeedV2ValidationReport:
    report = MasterSeedV2ValidationReport(total_rows=len(rows))

    skus = [row.get("sku", "").strip() for row in rows]
    report.unique_skus = len(set(skus))
    seen: set[str] = set()
    for sku in skus:
        if sku in seen:
            report.blocking_issues.append(
                ValidationIssue(sku, "duplicate_sku", "sku", f"{sku!r} appears more than once")
            )
        seen.add(sku)

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        gid = row.get("product_group_id", "").strip()
        if gid:
            groups.setdefault(gid, []).append(row)

    for row in rows:
        sku = row.get("sku", "").strip()
        is_review_row = row.get("record_state", "").strip() == "REVIEW"

        _check_three_digit_xw4(row, sku, report)
        _check_forbidden_words(row, sku, is_review_row, report)
        _check_brand(row, sku, report)
        _check_zusatzstimme_category(row, sku, report)

    for gid, group_rows in groups.items():
        if len(group_rows) < 2:
            continue
        _check_canonical_variant_count(gid, group_rows, report)
        _check_format_variant_title_equality(group_rows, report)

    return report


def _check_three_digit_xw4(row: dict[str, str], sku: str, report: MasterSeedV2ValidationReport) -> None:
    if _THREE_DIGIT_XW4.match(sku):
        report.blocking_issues.append(
            ValidationIssue(sku, "three_digit_xw4_canonical_sku", "sku", f"{sku!r} must be a 4-digit XW-4xxx SKU")
        )


def _check_forbidden_words(
    row: dict[str, str], sku: str, is_review_row: bool, report: MasterSeedV2ValidationReport
) -> None:
    for field_name in _TITLE_FIELDS:
        value = row.get(field_name, "")
        if not value:
            continue
        for word in _FORBIDDEN_WORDS:
            if word.lower() in value.lower():
                issue = ValidationIssue(
                    sku, "forbidden_word", field_name, f"{field_name} contains forbidden word {word!r}: {value!r}"
                )
                (report.known_review_issues if is_review_row else report.blocking_issues).append(issue)
                break


def _check_brand(row: dict[str, str], sku: str, report: MasterSeedV2ValidationReport) -> None:
    brand = row.get("brand", "").strip()
    if _BRAND_45.match(sku):
        expected = _BRAND_MNOZIL
    elif _BRAND_40.match(sku):
        expected = _BRAND_BLECHHAUFN
    elif _BRAND_123.match(sku):
        expected = _BRAND_XEISWORKS
    else:
        return
    if brand != expected:
        report.blocking_issues.append(
            ValidationIssue(sku, "brand_mismatch", "brand", f"expected {expected!r}, got {brand!r}")
        )


def _check_zusatzstimme_category(row: dict[str, str], sku: str, report: MasterSeedV2ValidationReport) -> None:
    if not _ZUSATZSTIMME_SKU.match(sku):
        return
    category = row.get("category_primary", "").strip()
    if category != _ZUSATZSTIMME_CATEGORY:
        report.blocking_issues.append(
            ValidationIssue(
                sku,
                "zusatzstimme_category_mismatch",
                "category_primary",
                f"expected {_ZUSATZSTIMME_CATEGORY!r}, got {category!r}",
            )
        )


def _check_canonical_variant_count(
    gid: str, group_rows: list[dict[str, str]], report: MasterSeedV2ValidationReport
) -> None:
    canonical = [row for row in group_rows if _truthy(row.get("canonical_variant", ""))]
    if len(canonical) != 1:
        skus = ", ".join(row.get("sku", "") for row in group_rows)
        report.blocking_issues.append(
            ValidationIssue(
                skus,
                "canonical_variant_count",
                "canonical_variant",
                f"group {gid} has {len(canonical)} canonical_variant=true rows, expected exactly 1",
            )
        )


def _check_format_variant_title_equality(
    group_rows: list[dict[str, str]], report: MasterSeedV2ValidationReport
) -> None:
    """Only ``title_full``/``title_short`` must match across *pure* FORMAT_VARIANT
    rows — ``code_short`` legitimately carries a format-specific suffix (e.g. ``_P``
    for Print@Home), confirmed against the actual V2 data (see test suite). A
    composite role like ``FORMAT_VARIANT|SCORING_VARIANT`` (e.g. a "Register-4er"
    digital edition) is a *different* arrangement, not merely a different format of
    the same content, so it is deliberately excluded — its title is expected to
    differ, same as a pure SCORING_VARIANT/ENSEMBLE_VARIANT row."""
    canonical_rows = [row for row in group_rows if _truthy(row.get("canonical_variant", ""))]
    if not canonical_rows:
        return
    canonical = canonical_rows[0]
    for row in group_rows:
        if row.get("variant_role", "").strip() != "FORMAT_VARIANT":
            continue
        for field_name in ("title_full", "title_short"):
            if row.get(field_name, "") != canonical.get(field_name, ""):
                report.blocking_issues.append(
                    ValidationIssue(
                        row.get("sku", ""),
                        "format_variant_title_mismatch",
                        field_name,
                        f"{field_name} {row.get(field_name)!r} != canonical {canonical.get(field_name)!r} "
                        f"({canonical.get('sku')})",
                    )
                )
