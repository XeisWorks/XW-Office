"""Applies the Master Seed V2 SKU-alias table to the canonical schema.

``XW_Product_Hub_SKU_Aliases_V2_2026-09-17.csv`` is authoritative for legacy-SKU
resolution (e.g. ``XW-443 -> XW-4043``). This runs *after* the master-seed batch has
been committed — every ``canonical_sku`` in the alias file must already exist as a
product/variant SKU — and creates one ``product_sku_alias`` row per alias pointing at
that canonical variant, via :meth:`ProductHubRepository.add_sku_alias`.

An alias never creates its own product or variant (that would silently double an
already-known product under two identities); a canonical SKU that can't be resolved is
reported as an error, never guessed at. Idempotent — re-running is a no-op for aliases
that already resolve to the same target (see ``add_sku_alias``).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from xw_office.repositories.product_hub import ProductHubRepository


@dataclass
class SkuAliasImportReport:
    total_rows: int = 0
    created: int = 0
    already_existed: int = 0
    errors: list[str] = field(default_factory=list)


def import_sku_aliases(
    session_factory: sessionmaker[Session],
    csv_path: str | Path,
    *,
    source: str = "master_seed_v2",
) -> SkuAliasImportReport:
    report = SkuAliasImportReport()
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    report.total_rows = len(rows)

    repo = ProductHubRepository(session_factory)
    for row in rows:
        alias_sku = (row.get("alias_sku") or "").strip()
        canonical_sku = (row.get("canonical_sku") or "").strip()
        if not alias_sku or not canonical_sku:
            report.errors.append(f"row missing alias_sku/canonical_sku: {row!r}")
            continue
        resolved = repo.resolve_sku(canonical_sku)
        if resolved is None:
            report.errors.append(f"{alias_sku}: canonical_sku {canonical_sku!r} does not resolve to a product")
            continue
        existing_before = repo.resolve_sku(alias_sku)
        try:
            repo.add_sku_alias(
                resolved.product.id,
                alias_sku=alias_sku,
                variant_id=resolved.variant.id,
                source=source,
            )
        except ValueError as exc:
            report.errors.append(f"{alias_sku}: {exc}")
            continue
        if existing_before is not None:
            report.already_existed += 1
        else:
            report.created += 1

    return report
