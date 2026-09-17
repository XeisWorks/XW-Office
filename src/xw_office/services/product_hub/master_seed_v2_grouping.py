"""Applies the Master Seed V2 curated grouping to already-committed, flat products.

The safe migration rule (see ``grouping.py``) means every seed row first becomes its
own product+variant (``import_commit.py``, unchanged). This module is the *second*
step: it reads the seed's own ``product_group_id``/``canonical_variant``/``parent_sku``/
``variant_role`` columns — never fuzzy matching, never inventing a grouping — and calls
the existing :class:`~xw_office.services.product_hub.grouping.GroupingService` once per
group: ``preview_grouping`` first, ``group_products_into_parent`` only if the preview is
safe (no channel-mapping conflicts). An unsafe or otherwise unresolvable group is
skipped and reported, never forced.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.grouping import GroupingConflictError, GroupingService


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class GroupPlan:
    group_id: str
    canonical_sku: str
    child_skus: list[str]


@dataclass
class GroupingApplyReport:
    groups_considered: int = 0
    groups_applied: int = 0
    groups_skipped_single_row: int = 0
    variants_moved: int = 0
    products_archived: int = 0
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def plan_groups_from_master_seed(rows: list[dict[str, str]]) -> list[GroupPlan]:
    """Pure planning step: from raw CSV rows to (canonical_sku, [child_skus]) per
    multi-row ``product_group_id``. No DB access, so this is trivially unit-testable
    and reusable for a dry-run preview before ever touching the database."""
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        gid = row.get("product_group_id", "").strip()
        if gid:
            groups.setdefault(gid, []).append(row)

    plans: list[GroupPlan] = []
    for gid, group_rows in groups.items():
        if len(group_rows) < 2:
            continue
        canonical_rows = [r for r in group_rows if _truthy(r.get("canonical_variant", ""))]
        if len(canonical_rows) != 1:
            # The validator already blocks this upstream; plan_groups is defensive,
            # not a second enforcement point — skip rather than guess which row wins.
            continue
        canonical_sku = canonical_rows[0]["sku"].strip()

        # Cross-check parent_sku (independent of canonical_variant) as the spec asks —
        # a disagreement means the seed itself is ambiguous about who the parent is;
        # skip rather than pick a side (empirically zero disagreements in the real V2
        # seed, but this is a real safety net, not dead code).
        disagreeing_parent_skus = {
            r.get("parent_sku", "").strip()
            for r in group_rows
            if r["sku"].strip() != canonical_sku and r.get("parent_sku", "").strip()
        }
        if disagreeing_parent_skus - {canonical_sku}:
            continue

        child_skus = [r["sku"].strip() for r in group_rows if r["sku"].strip() != canonical_sku]
        plans.append(GroupPlan(group_id=gid, canonical_sku=canonical_sku, child_skus=child_skus))
    return plans


def apply_master_seed_v2_grouping(
    session_factory: sessionmaker[Session],
    rows: list[dict[str, str]],
    *,
    actor: str = "",
) -> GroupingApplyReport:
    repo = ProductHubRepository(session_factory)
    grouping = GroupingService(session_factory)
    report = GroupingApplyReport()

    for plan in plan_groups_from_master_seed(rows):
        report.groups_considered += 1
        parent_resolved = repo.resolve_sku(plan.canonical_sku)
        if parent_resolved is None:
            report.errors.append(f"group {plan.group_id}: canonical sku {plan.canonical_sku!r} not found")
            continue

        child_product_ids: list[uuid.UUID] = []
        unresolved: list[str] = []
        for sku in plan.child_skus:
            resolved = repo.resolve_sku(sku)
            if resolved is None:
                unresolved.append(sku)
                continue
            if resolved.product.id == parent_resolved.product.id:
                continue  # already grouped (idempotent re-run)
            if resolved.product.id not in child_product_ids:
                child_product_ids.append(resolved.product.id)
        if unresolved:
            report.errors.append(f"group {plan.group_id}: unresolved child skus {unresolved}")
            continue
        if not child_product_ids:
            report.groups_skipped_single_row += 1
            continue

        preview = grouping.preview_grouping(
            parent_product_id=parent_resolved.product.id, child_product_ids=child_product_ids
        )
        if not preview.is_safe:
            report.conflicts.append(
                f"group {plan.group_id} ({plan.canonical_sku}): " + "; ".join(preview.channel_mapping_conflicts)
            )
            continue

        try:
            result = grouping.group_products_into_parent(
                parent_product_id=parent_resolved.product.id,
                child_product_ids=child_product_ids,
                actor=actor,
            )
        except GroupingConflictError as exc:
            report.conflicts.append(f"group {plan.group_id} ({plan.canonical_sku}): {exc}")
            continue
        except KeyError as exc:
            report.errors.append(f"group {plan.group_id}: {exc}")
            continue

        report.groups_applied += 1
        report.variants_moved += result.variants_moved
        report.products_archived += len(result.archived_child_product_ids)

    return report
