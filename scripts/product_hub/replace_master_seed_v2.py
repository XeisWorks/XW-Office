"""Replace the legacy (V1) Product Hub catalog with the reconciled Master Seed V2.

A repeatable, checked pipeline — see docs/product_hub/PROGRESS.md's "Master Seed V2"
section for the full write-up. Steps, in order:

1. validate the V2 CSV's hard invariants (aborts on any blocking issue)
2. check the current catalog is safe to replace (aborts on any non-automated edit)
3. delete the current (V1) catalog, FK-safe order
4. stage V2 rows (``MasterSeedImporter``, staging only)
5. run the matching engine as a safety check (product table is empty, so this should
   always report 0 conflicts/0 duplicates — a non-zero result here means step 3 didn't
   actually clear the table and this script stops rather than silently merging)
6. commit every staged row (``ImportCommitService`` — flat, one product per SKU)
7. apply the seed's own curated grouping (``product_group_id``/``canonical_variant``)
8. import the legacy SKU aliases
9. print a summary report and run the acceptance checks from the build request

Never pushes to Wix/sevdesk/Amazon — nothing in this pipeline calls an external client.

Usage::

    python scripts/product_hub/replace_master_seed_v2.py --database-url postgresql://... --yes

Without ``--yes`` this only validates + prints the replace-plan (dry run, no writes).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from xw_office.core.database import session_scope  # noqa: E402
from xw_office.models.base import Base  # noqa: E402
from xw_office.models.product_hub import ChannelMapping, Product  # noqa: E402
from xw_office.repositories.product_hub import ProductHubRepository  # noqa: E402
from xw_office.repositories.product_hub_import import ProductHubImportRepository  # noqa: E402
from xw_office.services.product_hub.import_commit import ImportCommitService  # noqa: E402
from xw_office.services.product_hub.master_seed_import import MasterSeedImporter  # noqa: E402
from xw_office.services.product_hub.master_seed_v2_grouping import apply_master_seed_v2_grouping  # noqa: E402
from xw_office.services.product_hub.master_seed_v2_replace import (  # noqa: E402
    check_catalog_replaceable,
    delete_legacy_master_seed_catalog,
)
from xw_office.services.product_hub.master_seed_v2_validate import (  # noqa: E402
    load_master_seed_v2_rows,
    validate_master_seed_v2_rows,
)
from xw_office.services.product_hub.matching import MatchingEngine  # noqa: E402
from xw_office.services.product_hub.sku_alias_import import import_sku_aliases  # noqa: E402

_DEFAULT_MASTER_SEED_CSV = ROOT / "docs" / "producthub_master-seed" / "XW_Product_Hub_Master_Seed_2026-09-17.csv"
_DEFAULT_ALIASES_CSV = ROOT / "docs" / "producthub_master-seed" / "XW_Product_Hub_SKU_Aliases_V2_2026-09-17.csv"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Postgres DSN (use the *public* URL if run off-Railway).")
    parser.add_argument("--master-seed-csv", default=str(_DEFAULT_MASTER_SEED_CSV))
    parser.add_argument("--aliases-csv", default=str(_DEFAULT_ALIASES_CSV))
    parser.add_argument("--actor", default="replace_master_seed_v2_script")
    parser.add_argument(
        "--yes", action="store_true", help="Actually perform the delete + import. Omit for a dry run."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    engine = create_engine(args.database_url, pool_pre_ping=True, future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    print("== 1. Validate V2 CSV ==")
    rows = load_master_seed_v2_rows(args.master_seed_csv)
    validation = validate_master_seed_v2_rows(rows)
    print(f"  rows={validation.total_rows} unique_skus={validation.unique_skus}")
    print(f"  blocking_issues={len(validation.blocking_issues)} known_review_issues={len(validation.known_review_issues)}")
    if not validation.is_valid:
        for issue in validation.blocking_issues:
            print(f"  BLOCKING {issue.sku}: {issue.rule} ({issue.field}) — {issue.detail}")
        print("Aborting — fix the seed file first.")
        return 2

    print("== 2. Check current catalog is safe to replace ==")
    replaceability = check_catalog_replaceable(session_factory)
    print(f"  current products={replaceability.product_count} variants={replaceability.variant_count}")
    if not replaceability.is_safe_to_replace:
        print(f"  BLOCKED: {replaceability.blocking_reason}")
        print("Aborting — no changes made.")
        return 3

    if not args.yes:
        print("\nDry run only (pass --yes to actually replace). No changes made.")
        return 0

    print("== 3. Delete legacy catalog ==")
    delete_report = delete_legacy_master_seed_catalog(session_factory, actor=args.actor)
    print(f"  products_deleted={delete_report.products_deleted} variants_deleted={delete_report.variants_deleted}")
    print(f"  improvements_deleted={delete_report.improvements_deleted} channel_mappings_deleted={delete_report.channel_mappings_deleted}")

    print("== 4. Stage V2 rows ==")
    import_repo = ProductHubImportRepository(session_factory)
    stage_report = MasterSeedImporter(import_repo=import_repo).run(args.master_seed_csv)
    print(f"  rows_staged={stage_report.rows_staged} errors={len(stage_report.errors)}")
    for err in stage_report.errors[:20]:
        print(f"  STAGE ERROR: {err}")

    print("== 5. Matching engine safety check ==")
    product_repo = ProductHubRepository(session_factory)
    matching_report = MatchingEngine(import_repo=import_repo, product_repo=product_repo).run(
        batch_id=stage_report.batch_id
    )
    print(
        f"  unmatched={matching_report.unmatched} suggested={matching_report.suggested_matches} "
        f"conflicts={len(matching_report.conflicts)} duplicates={len(matching_report.duplicates)}"
    )
    if matching_report.conflicts or matching_report.duplicates or matching_report.suggested_matches:
        print("  Unexpected non-empty-table match results — aborting before commit.")
        return 4

    print("== 6. Commit staged rows ==")
    commit_service = ImportCommitService(session_factory)
    commit_report = commit_service.commit_import_batch(stage_report.batch_id, actor=args.actor)
    print(
        f"  created={commit_report.created} linked={commit_report.linked} "
        f"already_committed={commit_report.already_committed} skipped_needs_review={commit_report.skipped_needs_review}"
    )
    for err in commit_report.errors[:20]:
        print(f"  COMMIT ERROR: {err}")

    print("== 7. Apply curated grouping ==")
    grouping_report = apply_master_seed_v2_grouping(session_factory, rows, actor=args.actor)
    print(
        f"  groups_considered={grouping_report.groups_considered} groups_applied={grouping_report.groups_applied} "
        f"variants_moved={grouping_report.variants_moved} products_archived={grouping_report.products_archived}"
    )
    for conflict in grouping_report.conflicts:
        print(f"  GROUPING CONFLICT: {conflict}")
    for err in grouping_report.errors:
        print(f"  GROUPING ERROR: {err}")

    print("== 8. Import SKU aliases ==")
    alias_report = import_sku_aliases(session_factory, args.aliases_csv, source="master_seed_v2")
    print(f"  total_rows={alias_report.total_rows} created={alias_report.created} already_existed={alias_report.already_existed}")
    for err in alias_report.errors[:20]:
        print(f"  ALIAS ERROR: {err}")

    print_summary(session_factory)
    run_acceptance_checks(session_factory)
    return 0


def print_summary(session_factory: sessionmaker[Session]) -> None:
    print("\n== Summary ==")
    with session_scope(session_factory) as session:
        product_count = session.scalar(select(func.count(Product.id))) or 0
        active_products = session.scalar(select(func.count(Product.id)).where(Product.archived_at.is_(None))) or 0
        by_status = dict(
            session.execute(
                select(Product.status, func.count(Product.id))
                .where(Product.archived_at.is_(None))
                .group_by(Product.status)
            ).all()
        )
        wix_mappings = session.scalar(
            select(func.count(ChannelMapping.id)).where(ChannelMapping.channel == "wix")
        ) or 0
    print(f"  products total (incl. archived groups)={product_count}")
    print(f"  products active/ungrouped-parent={active_products}")
    print(f"  status breakdown={by_status}")
    print(f"  wix channel_mappings={wix_mappings}")


def run_acceptance_checks(session_factory: sessionmaker[Session]) -> None:
    print("\n== Acceptance checks ==")
    repo = ProductHubRepository(session_factory)
    checks: list[tuple[str, bool]] = []

    r443 = repo.resolve_sku("XW-443")
    r4043 = repo.resolve_sku("XW-4043")
    checks.append(
        ("resolve_sku(XW-443) == resolve_sku(XW-4043)", bool(r443 and r4043 and r443.product.id == r4043.product.id))
    )
    checks.append(("XW-443 resolves only via alias, not a canonical variant SKU", bool(r443 and r443.matched_via == "alias")))

    r1025 = repo.resolve_sku("XW-102.5")
    r1025d = repo.resolve_sku("XW-102.5-D")
    checks.append(
        ("XW-102.5 and XW-102.5-D share one product", bool(r1025 and r1025d and r1025.product.id == r1025d.product.id))
    )
    checks.append(
        (
            "both named 'Volksmusik #2 - Tuba in B'",
            bool(r1025 and r1025.product.name == "Volksmusik #2 - Tuba in B"),
        )
    )

    r55101 = repo.resolve_sku("XW-551.01")
    r55101p = repo.resolve_sku("XW-551.01-P")
    checks.append(
        (
            "XW-551.01 and XW-551.01-P share one product + title",
            bool(
                r55101
                and r55101p
                and r55101.product.id == r55101p.product.id
                and r55101.product.name == r55101p.product.name
            ),
        )
    )

    r51116 = repo.get_product_by_sku("XW-511.16")
    r51117 = repo.get_product_by_sku("XW-511.17")
    checks.append(("XW-511.16 is draft/reserved", bool(r51116 and r51116.status == "draft")))
    checks.append(("XW-511.17 is active/live", bool(r51117 and r51117.status == "live")))

    r56212 = repo.get_product_by_sku("XW-562.12")
    checks.append(("XW-562.12 title contains '#2'", bool(r56212 and "#2" in r56212.name)))

    r40242 = repo.resolve_sku("XW-4024.2")
    r40243 = repo.resolve_sku("XW-4024.3")
    checks.append(
        (
            "XW-4024.2 and XW-4024.3 are grouped under one product as two distinct variants",
            bool(
                r40242
                and r40243
                and r40242.product.id == r40243.product.id
                and r40242.variant.id != r40243.variant.id
            ),
        )
    )

    for label, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    failed = [label for label, ok in checks if not ok]
    if failed:
        print(f"\n{len(failed)} acceptance check(s) failed: {failed}")


if __name__ == "__main__":
    raise SystemExit(main())
