"""Import Commit Service (PR06): atomically apply approved staging rows to the
canonical Product Hub schema.

Safety rules (docs/product_hub/XW_PRODUCT_HUB_CODEX_5_6_LUNA_BUILD_PLAN.md PR06):

- every commit runs in one DB transaction (one :func:`session_scope` per staging row);
- repeated commit of the same staging row is idempotent — ``StagingProduct.committed_product_id``
  is the anchor, a second commit call just returns the already-committed product;
- a fuzzy suggestion (``match_status='suggested_match'``) or an unresolved ``'conflict'``
  is never committed automatically — only ``'unmatched'``/``'rejected'`` (new product) or
  explicitly ``'approved'`` (link to an existing product) rows can become canonical writes;
- a genuine identifier conflict aborts that row's commit (raises ``CommitError``), it is
  never silently resolved;
- every commit writes an ``audit_log`` entry.

Excel-sourced rows also get a ``product_price`` row (``RETAIL_EUR``, gross from the
sheet's ``brutto`` column, net computed at the fixed 10% VAT rate — see
``excel_import.py``): now that netto is deterministic rather than ambiguous, there is
no longer a reason to defer this to a separate manual step. Idempotent like everything
else here — only written if the variant has no current ``RETAIL_EUR`` price yet.
"""
from __future__ import annotations

from decimal import Decimal
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import Product, ProductIdentifier
from xw_office.models.product_hub_import import StagingProduct
from xw_office.repositories.product_hub import ProductHubRepository, slugify
from xw_office.repositories.product_hub_import import (
    ProductHubImportRepository,
    StagingProductFilter,
)

#: Only these statuses may create a brand-new canonical product.
_COMMITTABLE_FOR_CREATE = ("unmatched", "rejected")
#: Only this status may link a staged row to an existing product.
_COMMITTABLE_FOR_LINK = ("approved",)
#: These require an explicit human decision (approve_match/reject_match) first.
_NEVER_AUTO_COMMIT = ("suggested_match", "conflict", "exact_match")


class CommitError(RuntimeError):
    """Raised when a staging row cannot be safely committed as-is."""


@dataclass(frozen=True)
class CommitPreview:
    """What committing one staging row would do, without writing anything."""

    staging_product_id: uuid.UUID
    action: str  # "create" | "link_existing" | "already_committed" | "blocked"
    target_product_id: uuid.UUID | None
    target_product_name: str | None
    staged_identifiers: int
    staged_assets: int
    suggested_tags: list[str]
    blocked_reason: str | None = None


@dataclass
class BatchCommitReport:
    """Outcome of one :meth:`ImportCommitService.commit_import_batch` call."""

    batch_id: uuid.UUID
    created: int = 0
    linked: int = 0
    already_committed: int = 0
    skipped_needs_review: int = 0
    errors: list[str] = field(default_factory=list)


class ImportCommitService:
    """Turns reviewed staging rows into canonical products, one row per transaction."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- match decisions (human review step) -------------------------------------

    def approve_match(self, staging_product_id: uuid.UUID, *, actor: str = "") -> StagingProduct:
        with session_scope(self._session_factory) as session:
            import_repo = ProductHubImportRepository(session)
            staging = import_repo.get_staging_product(staging_product_id)
            if staging is None:
                raise KeyError(f"Staging product {staging_product_id} not found")
            if staging.match_status not in ("exact_match", "suggested_match"):
                raise CommitError(f"Cannot approve a match in status {staging.match_status!r}")
            updated = import_repo.set_match(
                staging_product_id,
                match_status="approved",
                proposed_product_id=staging.proposed_product_id,
                proposed_variant_id=staging.proposed_variant_id,
                match_method=staging.match_method,
                match_score=staging.match_score,
            )
            ProductHubRepository(session).record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="staging_product",
                entity_id=staging_product_id,
                action="approve_match",
                source=staging.source,
                after_data={"proposed_product_id": str(staging.proposed_product_id)},
            )
            return updated

    def reject_match(
        self, staging_product_id: uuid.UUID, *, actor: str = "", note: str = ""
    ) -> StagingProduct:
        with session_scope(self._session_factory) as session:
            import_repo = ProductHubImportRepository(session)
            staging = import_repo.get_staging_product(staging_product_id)
            if staging is None:
                raise KeyError(f"Staging product {staging_product_id} not found")
            updated = import_repo.set_match(
                staging_product_id, match_status="rejected", decision_note=note
            )
            ProductHubRepository(session).record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="staging_product",
                entity_id=staging_product_id,
                action="reject_match",
                source=staging.source,
                after_data={"note": note},
            )
            return updated

    # -- preview ------------------------------------------------------------------

    def preview_commit(self, staging_product_id: uuid.UUID) -> CommitPreview:
        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            import_repo = ProductHubImportRepository(session)
            staging = import_repo.get_staging_product(staging_product_id)
            if staging is None:
                raise KeyError(f"Staging product {staging_product_id} not found")

            tags = _suggested_tags(staging)

            if staging.committed_product_id is not None:
                product = product_repo.get_product(staging.committed_product_id)
                return CommitPreview(
                    staging_product_id=staging.id,
                    action="already_committed",
                    target_product_id=staging.committed_product_id,
                    target_product_name=product.name if product else None,
                    staged_identifiers=0,
                    staged_assets=0,
                    suggested_tags=tags,
                )

            if staging.match_status in _NEVER_AUTO_COMMIT:
                return CommitPreview(
                    staging_product_id=staging.id,
                    action="blocked",
                    target_product_id=staging.proposed_product_id,
                    target_product_name=None,
                    staged_identifiers=0,
                    staged_assets=0,
                    suggested_tags=tags,
                    blocked_reason=(
                        f"status {staging.match_status!r} needs approve_match/reject_match first"
                    ),
                )

            if staging.match_status == "approved" and staging.proposed_product_id is not None:
                product = product_repo.get_product(staging.proposed_product_id)
                action, target_id, target_name = (
                    "link_existing",
                    staging.proposed_product_id,
                    product.name if product else None,
                )
            else:
                action, target_id, target_name = "create", None, None

            return CommitPreview(
                staging_product_id=staging.id,
                action=action,
                target_product_id=target_id,
                target_product_name=target_name,
                staged_identifiers=len(import_repo.list_identifiers(staging.id)),
                staged_assets=len(import_repo.list_assets(staging.id)),
                suggested_tags=tags,
            )

    # -- commit ---------------------------------------------------------------------

    def create_from_staging(self, staging_product_id: uuid.UUID, *, actor: str = "") -> Product:
        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            import_repo = ProductHubImportRepository(session)
            staging = import_repo.get_staging_product(staging_product_id)
            if staging is None:
                raise KeyError(f"Staging product {staging_product_id} not found")

            already = self._already_committed(product_repo, staging)
            if already is not None:
                return already

            if staging.match_status not in _COMMITTABLE_FOR_CREATE:
                raise CommitError(
                    f"Cannot create a new product from staging row in status "
                    f"{staging.match_status!r} — approve or reject its proposed match first"
                )
            if not staging.sku:
                raise CommitError("Cannot create a canonical product without a SKU")

            fields = staging.normalized_fields
            stock_enabled = fields.get("stock_enabled")
            product, _variant = product_repo.create_product(
                sku=staging.sku,
                name=staging.name or staging.sku,
                stock_enabled=stock_enabled if isinstance(stock_enabled, bool) else True,
                status=str(fields.get("status")) if fields.get("status") else "draft",
                product_type=str(fields.get("product_type")) if fields.get("product_type") else "physical",
                brand_name=str(fields.get("brand") or ""),
                category=str(fields.get("category") or ""),
                description=str(fields.get("description") or ""),
            )
            if fields.get("active") is False:
                product_repo.update_product(product.id, expected_row_version=product.row_version, active=False)

            self._merge_staging_extras(product_repo, import_repo, staging, product)
            import_repo.mark_committed(staging.id, product_id=product.id)

            product_repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product.id,
                action="create_from_staging",
                source=staging.source,
                after_data={"sku": product.sku, "name": product.name, "staging_product_id": str(staging.id)},
            )
            return product

    def commit_approved_match(self, staging_product_id: uuid.UUID, *, actor: str = "") -> Product:
        with session_scope(self._session_factory) as session:
            product_repo = ProductHubRepository(session)
            import_repo = ProductHubImportRepository(session)
            staging = import_repo.get_staging_product(staging_product_id)
            if staging is None:
                raise KeyError(f"Staging product {staging_product_id} not found")

            already = self._already_committed(product_repo, staging)
            if already is not None:
                return already

            if staging.match_status not in _COMMITTABLE_FOR_LINK:
                raise CommitError(
                    f"Cannot commit a link for staging row in status {staging.match_status!r} "
                    "— call approve_match first"
                )
            if staging.proposed_product_id is None:
                raise CommitError("Approved staging row has no proposed_product_id")

            product = product_repo.get_product(staging.proposed_product_id)
            if product is None:
                raise CommitError(f"Proposed product {staging.proposed_product_id} no longer exists")

            self._merge_staging_extras(product_repo, import_repo, staging, product)
            import_repo.mark_committed(staging.id, product_id=product.id)

            product_repo.record_audit(
                actor_type="user" if actor else "system",
                actor_id=actor,
                entity_type="product",
                entity_id=product.id,
                action="commit_approved_match",
                source=staging.source,
                after_data={"staging_product_id": str(staging.id)},
            )
            return product

    def commit_import_batch(self, batch_id: uuid.UUID, *, actor: str = "") -> BatchCommitReport:
        """Commit every safely-committable row in a batch; idempotent and per-row atomic.

        ``unmatched`` rows are created automatically (the "safe 1:1 import" rule — there
        is no ambiguity to resolve). ``approved`` rows are linked. Everything else
        (``suggested_match``, ``conflict``, ``rejected``) needs an explicit human/command
        decision first and is reported as skipped, never guessed at.
        """
        import_repo = ProductHubImportRepository(self._session_factory)
        rows = import_repo.list_staging_products(StagingProductFilter(import_batch_id=batch_id))
        report = BatchCommitReport(batch_id=batch_id)

        for staging in rows:
            if staging.match_status == "committed":
                report.already_committed += 1
                continue
            if staging.match_status == "unmatched":
                try:
                    self.create_from_staging(staging.id, actor=actor)
                    report.created += 1
                except CommitError as exc:
                    report.errors.append(f"{staging.source}:{staging.source_key}: {exc}")
                continue
            if staging.match_status == "approved":
                try:
                    self.commit_approved_match(staging.id, actor=actor)
                    report.linked += 1
                except CommitError as exc:
                    report.errors.append(f"{staging.source}:{staging.source_key}: {exc}")
                continue
            report.skipped_needs_review += 1

        return report

    # -- internal -----------------------------------------------------------------

    @staticmethod
    def _already_committed(product_repo: ProductHubRepository, staging: StagingProduct) -> Product | None:
        if staging.committed_product_id is None:
            return None
        return product_repo.get_product(staging.committed_product_id)

    def _merge_staging_extras(
        self,
        product_repo: ProductHubRepository,
        import_repo: ProductHubImportRepository,
        staging: StagingProduct,
        product: Product,
    ) -> None:
        """Enrich *product* with staged identifiers/assets/categories/tags.

        Idempotent (safe to run again on an already-enriched product) and conservative:
        never overwrites an existing field, only adds what is missing; raises
        :class:`CommitError` on a genuine identifier conflict instead of guessing.
        """
        if staging.source in ("wix", "sevdesk") and staging.source_external_id:
            existing_mapping = product_repo.get_channel_mapping(
                channel=staging.source, entity_type="product", external_id=staging.source_external_id
            )
            if existing_mapping is None:
                product_repo.create_channel_mapping(
                    channel=staging.source,
                    entity_type="product",
                    internal_entity_id=product.id,
                    external_id=staging.source_external_id,
                )

        for staged_identifier in import_repo.list_identifiers(staging.id):
            existing = product_repo.find_identifier(
                scheme=staged_identifier.scheme, normalized_value=staged_identifier.normalized_value
            )
            if existing is not None:
                owner_product_id = _identifier_owner_product_id(product_repo, existing)
                if owner_product_id != product.id:
                    raise CommitError(
                        f"Identifier {staged_identifier.scheme}:{staged_identifier.value} already "
                        f"belongs to a different product ({owner_product_id})"
                    )
                continue
            product_repo.add_identifier(
                product_id=product.id,
                scheme=staged_identifier.scheme,
                value=staged_identifier.value,
                normalized_value=staged_identifier.normalized_value,
            )

        existing_assets = product_repo.list_assets(product.id)
        for staged_asset in import_repo.list_assets(staging.id):
            duplicate = staged_asset.source_external_id and any(
                existing.role == staged_asset.role
                and existing.source_external_id == staged_asset.source_external_id
                for existing in existing_assets
            )
            if duplicate:
                continue
            product_repo.add_asset(
                product_id=product.id,
                role=staged_asset.role,
                storage_kind="EXTERNAL_URL",
                uri=staged_asset.source_url or "",
                sort_order=staged_asset.sort_order,
                source_channel=staging.source,
                source_external_id=staged_asset.source_external_id,
                source_url=staged_asset.source_url,
            )

        # Excel/master-seed categories are the business's own taxonomy - safe to become
        # internal categories directly. Wix/sevdesk staged categories stay in staging
        # for a later, deliberate channel-category-mapping curation step (mixing them
        # in here would conflate external channel taxonomy with the internal one).
        if staging.source in ("excel", "master_seed"):
            existing_category_ids = {link.category_id for link in product_repo.list_product_categories(product.id)}
            for staged_category in import_repo.list_categories(staging.id):
                if not staged_category.external_category_name:
                    continue
                code = staged_category.external_category_id or slugify(staged_category.external_category_name)
                category = product_repo.get_or_create_category(code=code, name=staged_category.external_category_name)
                if category.id not in existing_category_ids:
                    product_repo.add_product_category(product_id=product.id, category_id=category.id)
                    existing_category_ids.add(category.id)

        for tag_label in _suggested_tags(staging):
            existing_tag_ids = {link.tag_id for link in product_repo.list_product_tags(product.id)}
            tag = product_repo.get_or_create_tag(code=slugify(tag_label), label=tag_label)
            if tag.id not in existing_tag_ids:
                product_repo.add_product_tag(product_id=product.id, tag_id=tag.id)

        if staging.source in ("excel", "master_seed"):
            brutto_raw = staging.normalized_fields.get("brutto")
            price_list = product_repo.get_price_list_by_code("RETAIL_EUR")
            variant = product_repo.get_default_variant(product.id)
            if brutto_raw and price_list is not None and variant is not None:
                has_current_price = any(
                    price.price_list_id == price_list.id and price.valid_until is None
                    for price in product_repo.list_prices(variant.id)
                )
                if not has_current_price:
                    netto_raw = staging.normalized_fields.get("netto")
                    tax_rate_raw = staging.normalized_fields.get("tax_rate")
                    product_repo.set_price(
                        variant.id,
                        price_list_id=price_list.id,
                        gross_amount=Decimal(str(brutto_raw)),
                        net_amount=Decimal(str(netto_raw)) if netto_raw else None,
                        tax_rate=Decimal(str(tax_rate_raw)) if tax_rate_raw else None,
                        source=f"{staging.source}_import",
                    )

        if staging.source == "master_seed":
            self._merge_master_seed_extras(product_repo, staging, product)

    def _merge_master_seed_extras(
        self, product_repo: ProductHubRepository, staging: StagingProduct, product: Product
    ) -> None:
        """Master-seed-only enrichment: Wix linkage (only when the seed already knows
        the Wix handle — never guessed), an editorial-review flag for AUTO_DRAFT
        content, and the extra music/grouping metadata the canonical schema has no
        dedicated columns for yet (parked in ``product.attributes``, conservative —
        never overwrites a key that's already set)."""
        fields = staging.normalized_fields

        wix_handle_id = fields.get("wix_handle_id")
        if isinstance(wix_handle_id, str) and wix_handle_id:
            existing_mapping = product_repo.get_channel_mapping(
                channel="wix", entity_type="product", external_id=wix_handle_id
            )
            if existing_mapping is None:
                product_repo.create_channel_mapping(
                    channel="wix",
                    entity_type="product",
                    internal_entity_id=product.id,
                    external_id=wix_handle_id,
                    sync_status="never",
                )

        if fields.get("content_status") == "AUTO_DRAFT":
            already_flagged = any(
                imp.source == "master_seed_import" and imp.status == "open"
                for imp in product_repo.list_improvements(product.id)
            )
            if not already_flagged:
                product_repo.create_improvement(
                    product_id=product.id,
                    description=(
                        "Automatisch generierte Beschreibung/Bulletpoints aus dem "
                        "Master-Seed-Import — vor Push zu Wix/Amazon redaktionell prüfen."
                    ),
                    source="master_seed_import",
                    severity="minor",
                )

        attribute_keys = (
            "title_short",
            "code_short",
            "bullet_points",
            "music_attributes",
            "erp_category",
            "parent_sku",
            "product_group_id",
            "group_key",
            "grouping_confidence",
            "conflict_flags",
            "conflict_notes",
            # -- V2 additions — purely informational/traceability, never auto-acted on --
            "canonical_sku",
            "legacy_sku_aliases",
            "canonical_variant",
            "variant_role",
            "arrangement_variant",
            "review_required",
            "sot_status",
            "derived_from_sku",
            "sync_wix",
            "sync_sevdesk",
            "sync_amazon",
            "wix_publish_eligible",
            "channel_cleanup_required",
            "channel_cleanup_notes",
        )
        updates = {
            key: fields[key]
            for key in attribute_keys
            if fields.get(key) not in (None, "", [], {}) and key not in product.attributes
        }
        if updates:
            merged_attributes = {**product.attributes, **updates}
            product_repo.update_product(
                product.id, expected_row_version=product.row_version, attributes=merged_attributes
            )


def _suggested_tags(staging: StagingProduct) -> list[str]:
    raw = staging.normalized_fields.get("suggested_tags")
    if not isinstance(raw, list):
        return []
    return [tag for tag in raw if isinstance(tag, str) and tag.strip()]


def _identifier_owner_product_id(
    product_repo: ProductHubRepository, identifier: ProductIdentifier
) -> uuid.UUID | None:
    if identifier.product_id is not None:
        return identifier.product_id
    if identifier.variant_id is not None:
        variant = product_repo.get_variant(identifier.variant_id)
        return variant.product_id if variant is not None else None
    return None
