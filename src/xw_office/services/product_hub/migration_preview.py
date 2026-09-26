"""Read-only preview for moving legacy inventory settings onto Product Hub.

This deliberately does not call any repository method that writes.  It makes the
cutover evidence repeatable without turning a report into an implicit migration.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any

from xw_office.repositories.product_hub import normalize_sku


@dataclass(frozen=True)
class HubVariantSnapshot:
    product_id: str
    variant_id: str
    sku: str
    is_default: bool = False


@dataclass(frozen=True)
class HubAliasSnapshot:
    product_id: str
    variant_id: str | None
    alias_sku: str


@dataclass(frozen=True)
class HubPrintAssetSnapshot:
    product_id: str
    variant_id: str | None
    uri: str


@dataclass(frozen=True)
class MigrationPreviewEntry:
    legacy_sku: str
    legacy_name: str
    status: str
    match_method: str | None
    product_id: str | None
    variant_id: str | None
    print_path: str
    print_status: str
    title_print_config_count: int
    alias_mappings: list[str]
    notes: list[str]


def build_migration_preview(
    legacy_products: list[object],
    *,
    variants: list[HubVariantSnapshot],
    aliases: list[HubAliasSnapshot],
    print_assets: list[HubPrintAssetSnapshot],
) -> list[MigrationPreviewEntry]:
    """Match legacy rows exactly by SKU or Hub alias, without fuzzy matching.

    Duplicate legacy SKUs are intentionally marked ``ambiguous_legacy_sku`` even
    when the Hub resolves them: selecting one would silently lose divergent print
    settings.  Title-specific print configurations are likewise preserved as a
    manual-review obligation because the current Hub print rule is variant scoped.
    """
    normalized_counts = Counter(
        normalize_sku(_as_text(_field(row, "sku")))
        for row in legacy_products
        if normalize_sku(_as_text(_field(row, "sku")))
    )
    variant_by_sku = {normalize_sku(row.sku): row for row in variants}
    alias_by_sku = {normalize_sku(row.alias_sku): row for row in aliases}
    aliases_by_product: dict[str, list[str]] = defaultdict(list)
    for alias in aliases:
        aliases_by_product[alias.product_id].append(alias.alias_sku)
    default_variant_by_product = {
        row.product_id: row for row in variants if row.is_default
    }
    assets_by_product: dict[str, set[tuple[str | None, str]]] = defaultdict(set)
    for asset in print_assets:
        assets_by_product[asset.product_id].add((asset.variant_id, asset.uri.strip()))

    entries: list[MigrationPreviewEntry] = []
    for raw in legacy_products:
        sku = normalize_sku(_as_text(_field(raw, "sku")))
        name = _as_text(_field(raw, "name"))
        print_path = _as_text(_field(raw, "print_file_path"))
        title_configs = _field(raw, "title_print_configs")
        title_config_count = len(title_configs) if isinstance(title_configs, dict) else 0
        notes: list[str] = []
        matched = variant_by_sku.get(sku) if sku else None
        method = "exact_sku" if matched else None
        if matched is None and sku:
            alias = alias_by_sku.get(sku)
            if alias is not None:
                target = alias.variant_id or (
                    default_variant_by_product.get(alias.product_id).variant_id
                    if alias.product_id in default_variant_by_product
                    else ""
                )
                matched = HubVariantSnapshot(
                    product_id=alias.product_id,
                    variant_id=target,
                    sku=sku,
                )
                method = "sku_alias"

        if not sku:
            status, print_status = "invalid_legacy_sku", "not_assessed"
            notes.append("Legacy row has no SKU and cannot be matched automatically.")
        elif normalized_counts[sku] > 1:
            status, print_status = "ambiguous_legacy_sku", "manual_review"
            notes.append("More than one legacy row normalizes to this SKU.")
        elif matched is None or not matched.variant_id:
            status, print_status = "unmatched", "manual_review"
            notes.append("No exact Hub SKU or unambiguous Hub alias exists.")
        else:
            status = "matched"
            if not print_path:
                print_status = "no_legacy_print_path"
            elif (matched.variant_id, print_path) in assets_by_product[matched.product_id] or (
                None,
                print_path,
            ) in assets_by_product[matched.product_id]:
                print_status = "already_mirrored"
            else:
                print_status = "mirror_required"
                notes.append("Legacy print path is not yet a Hub PRINT_PDF asset.")
            if title_config_count:
                notes.append(
                    "Title-specific print configuration requires manual mapping; "
                    "current Hub print rules are variant scoped."
                )

        entries.append(
            MigrationPreviewEntry(
                legacy_sku=sku,
                legacy_name=name,
                status=status,
                match_method=method,
                product_id=matched.product_id if matched and status == "matched" else None,
                variant_id=matched.variant_id if matched and status == "matched" else None,
                print_path=print_path,
                print_status=print_status,
                title_print_config_count=title_config_count,
                alias_mappings=sorted(aliases_by_product.get(matched.product_id, [])) if matched else [],
                notes=notes,
            )
        )
    return entries


def preview_payload(entries: list[MigrationPreviewEntry]) -> dict[str, object]:
    """Return a stable JSON-ready report including all relevant aggregate counts."""
    return {
        "summary": {
            "legacy_rows": len(entries),
            "by_status": dict(sorted(Counter(entry.status for entry in entries).items())),
            "by_print_status": dict(sorted(Counter(entry.print_status for entry in entries).items())),
            "alias_mappings_listed": sum(len(entry.alias_mappings) for entry in entries),
        },
        "entries": [asdict(entry) for entry in entries],
    }


def _field(row: object, name: str) -> object:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _as_text(value: object) -> str:
    return str(value or "").strip()
