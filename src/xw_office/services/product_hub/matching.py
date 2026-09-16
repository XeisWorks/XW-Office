"""Cross-source SKU/identifier/fuzzy matching engine (PR05 continued).

Resolves staged rows (Wix/sevdesk/Excel — PR03/PR04/PR05) against the canonical
schema (PR01) in strict priority order and never auto-merges anything below "exact"
certainty, per docs/product_hub/XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md PR05:

1. existing ``channel_mapping.external_id`` (source is wix/sevdesk and already linked)
2. exact normalized SKU (``product_variant.sku``)
3. SKU alias (``product_sku_alias``)
4. unique identifier (ISBN/EAN/ASIN/...) (``product_identifier``)
5. fuzzy name similarity — **suggestion only**, written as ``import_match_candidate``
   rows, never auto-applied as a match.

This only ever writes ``match_status``/``proposed_product_id``/... via
:meth:`~xw_office.repositories.product_hub_import.ProductHubImportRepository.set_match`
and ``import_match_candidate`` rows — never a canonical table. Committing a match is a
separate, explicit, human-reviewed step (PR06).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from xw_office.models.product_hub_import import StagingProduct
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.product_hub_import import (
    ProductHubImportRepository,
    StagingProductFilter,
)

logger = logging.getLogger(__name__)

#: rapidfuzz WRatio (0-100). Below this, a staged row stays "unmatched" rather than
#: getting a low-confidence fuzzy suggestion nobody asked for.
_FUZZY_SUGGEST_THRESHOLD = 80.0
_MAX_FUZZY_CANDIDATES = 3
#: Below this similarity, flag staged-vs-matched-product name drift for manual review.
_TITLE_DRIFT_THRESHOLD = 90.0


@dataclass
class MatchingReport:
    """The "Import-Review-Bericht" the build plan asks PR05 to produce."""

    rows_considered: int = 0
    exact_external_id: int = 0
    exact_sku: int = 0
    alias_sku: int = 0
    identifier_matches: int = 0
    suggested_matches: int = 0
    unmatched: int = 0
    conflicts: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    title_drift: list[str] = field(default_factory=list)


class MatchingEngine:
    """Read staging rows, propose/record matches against the canonical schema."""

    def __init__(
        self,
        *,
        import_repo: ProductHubImportRepository,
        product_repo: ProductHubRepository,
    ) -> None:
        self._import_repo = import_repo
        self._product_repo = product_repo

    def run(self, *, batch_id: uuid.UUID | None = None) -> MatchingReport:
        """Match every staged row (optionally limited to one batch) against the hub."""
        filters = StagingProductFilter(import_batch_id=batch_id) if batch_id else None
        staging_rows = self._import_repo.list_staging_products(filters)
        report = MatchingReport(rows_considered=len(staging_rows))

        # Track which canonical product each staged row in *this run* resolved to, so
        # two different staged rows both claiming the same product are flagged.
        claimed_by_product: dict[uuid.UUID, list[str]] = {}

        for staging in staging_rows:
            row_key = f"{staging.source}:{staging.source_key}"
            try:
                self._match_one(staging, row_key, report, claimed_by_product)
            except Exception:  # noqa: BLE001 - one bad row must not abort the run
                logger.exception("Matching failed for staging product %s", staging.id)
                report.unmatched += 1

        for product_id, keys in claimed_by_product.items():
            if len(keys) > 1:
                report.duplicates.append(
                    f"product {product_id} claimed by staged rows: {', '.join(sorted(keys))}"
                )

        return report

    def _match_one(
        self,
        staging: StagingProduct,
        row_key: str,
        report: MatchingReport,
        claimed_by_product: dict[uuid.UUID, list[str]],
    ) -> None:
        by_channel = self._match_by_channel_mapping(staging)
        if by_channel is not None:
            self._record_exact_match(staging, by_channel, "existing_external_id", row_key, claimed_by_product)
            report.exact_external_id += 1
            return

        if staging.sku:
            resolved = self._product_repo.resolve_sku(staging.sku)
            if resolved is not None:
                method = "exact_sku" if resolved.matched_via == "sku" else "sku_alias"
                self._record_exact_match(staging, resolved.product.id, method, row_key, claimed_by_product)
                if method == "exact_sku":
                    report.exact_sku += 1
                else:
                    report.alias_sku += 1
                self._check_title_drift(staging, resolved.product.name, row_key, report)
                return

        identifier_result = self._match_by_identifier(staging)
        if identifier_result is not None:
            product_id, is_conflict = identifier_result
            if is_conflict or product_id is None:
                self._import_repo.set_match(staging.id, match_status="conflict")
                report.conflicts.append(
                    f"{row_key}: staged identifiers resolve to more than one existing product"
                )
                return
            self._record_exact_match(staging, product_id, "identifier", row_key, claimed_by_product)
            report.identifier_matches += 1
            return

        candidates = self._fuzzy_candidates(staging)
        if candidates:
            for rank, (product_id, score) in enumerate(candidates, start=1):
                self._import_repo.add_match_candidate(
                    staging.id,
                    candidate_product_id=product_id,
                    match_method="fuzzy_suggested",
                    match_score=score / 100.0,
                    rank=rank,
                )
            self._import_repo.set_match(
                staging.id,
                match_status="suggested_match",
                match_method="fuzzy_suggested",
                match_score=candidates[0][1] / 100.0,
            )
            report.suggested_matches += 1
            return

        self._import_repo.set_match(staging.id, match_status="unmatched")
        report.unmatched += 1

    def _record_exact_match(
        self,
        staging: StagingProduct,
        product_id: uuid.UUID,
        method: str,
        row_key: str,
        claimed_by_product: dict[uuid.UUID, list[str]],
    ) -> None:
        self._import_repo.set_match(
            staging.id,
            match_status="exact_match",
            proposed_product_id=product_id,
            match_method=method,
            match_score=1.0,
        )
        claimed_by_product.setdefault(product_id, []).append(row_key)

    def _match_by_channel_mapping(self, staging: StagingProduct) -> uuid.UUID | None:
        if staging.source not in ("wix", "sevdesk") or not staging.source_external_id:
            return None
        mapping = self._product_repo.get_channel_mapping(
            channel=staging.source,
            entity_type="product",
            external_id=staging.source_external_id,
        )
        return mapping.internal_entity_id if mapping is not None else None

    def _match_by_identifier(self, staging: StagingProduct) -> tuple[uuid.UUID | None, bool] | None:
        """Resolve via this row's staged identifiers.

        A "conflict" here means the row's *own* identifiers disagree with each other —
        e.g. its ASIN resolves to canonical product A while its ISBN resolves to a
        different canonical product B. A single identifier simply matching an existing
        product is a normal, trustworthy tier-4 match, not a conflict.
        """
        resolved_product_ids: set[uuid.UUID] = set()
        for staged_identifier in self._import_repo.list_identifiers(staging.id):
            canonical = self._product_repo.find_identifier(
                scheme=staged_identifier.scheme,
                normalized_value=staged_identifier.normalized_value,
            )
            if canonical is None:
                continue
            product_id = canonical.product_id
            if product_id is None and canonical.variant_id is not None:
                variant = self._product_repo.get_variant(canonical.variant_id)
                product_id = variant.product_id if variant is not None else None
            if product_id is not None:
                resolved_product_ids.add(product_id)

        if not resolved_product_ids:
            return None
        if len(resolved_product_ids) > 1:
            return None, True
        return next(iter(resolved_product_ids)), False

    def _fuzzy_candidates(self, staging: StagingProduct) -> list[tuple[uuid.UUID, float]]:
        if not staging.name:
            return []
        scored: list[tuple[uuid.UUID, float]] = []
        for product in self._product_repo.list_products():
            score = fuzz.WRatio(staging.name, product.name)
            if score >= _FUZZY_SUGGEST_THRESHOLD:
                scored.append((product.id, score))
        scored.sort(key=lambda item: -item[1])
        return scored[:_MAX_FUZZY_CANDIDATES]

    def _check_title_drift(
        self, staging: StagingProduct, canonical_name: str, row_key: str, report: MatchingReport
    ) -> None:
        if not staging.name or not canonical_name:
            return
        score = fuzz.WRatio(staging.name, canonical_name)
        if score < _TITLE_DRIFT_THRESHOLD:
            report.title_drift.append(
                f"{row_key}: staged name {staging.name!r} vs canonical {canonical_name!r} "
                f"(similarity {score:.0f})"
            )
