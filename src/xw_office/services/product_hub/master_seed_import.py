"""Master-seed CSV importer (2026-09-17): the reconciled XeisWorks/MusikHeroes catalog.

Unlike ``excel_import.py`` (which parses the raw ``Produktpalette`` sheet directly and
was the wrong source of truth for a full catalog load — it doesn't carry the
``XeisWorks``/``MusikHeroes`` sheets), this reads an already-reconciled, externally
prepared CSV (``docs/producthub_master-seed/``) that cross-references XLSX/Wix/sevdesk/
Amazon and resolves most drift itself. See that folder's own README for the exact
source-of-truth rules and modeling decisions — this importer trusts them and stages
data, it does not re-derive them.

Never writes to a canonical table — staging only, same "explicit commit step" rule as
every other Product Hub importer.
"""
from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from xw_office.repositories.product_hub_import import ProductHubImportRepository

logger = logging.getLogger(__name__)

#: Rows with this record_state have no XLSX/Wix presence — sevdesk-only operational
#: line items (shipping options, credits, artist-fee bookings, ...), never meant for
#: sale on any channel. Tagged distinctly so B2B/Wix-readiness views can exclude them
#: rather than flagging "missing Wix mapping" as a problem for something that was
#: never supposed to have one.
_NOT_FOR_SALE_RECORD_STATE = "EXTERNAL_ONLY"
_NOT_FOR_SALE_TAG = "Nicht zum Verkauf"

_IDENTIFIER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("isbn13", "ISBN13"),
    ("isbn10", "ISBN10"),
    ("ean", "EAN"),
)
_BULLET_COLUMNS = (
    "bullet_point_1",
    "bullet_point_2",
    "bullet_point_3",
    "bullet_point_4",
    "bullet_point_5",
)
_MUSIC_ATTRIBUTE_COLUMNS = (
    "instrument",
    "voice",
    "transposition",
    "register",
    "clef",
    "ensemble",
    "scoring",
    "voice_count",
)


@dataclass
class MasterSeedImportReport:
    batch_id: uuid.UUID
    rows_staged: int = 0
    identifiers_staged: int = 0
    not_for_sale_count: int = 0
    auto_draft_content_count: int = 0
    errors: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _to_decimal(value: str | None) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _to_int(value: str | None) -> int | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return int(Decimal(text))
    except InvalidOperation:
        return None


def _to_bool(value: str | None) -> bool | None:
    text = _clean(value).lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


class MasterSeedImporter:
    """Reads the reconciled master-seed CSV into staging."""

    def __init__(self, *, import_repo: ProductHubImportRepository) -> None:
        self._import_repo = import_repo

    def run(self, csv_path: str | Path) -> MasterSeedImportReport:
        path = Path(csv_path)
        batch = self._import_repo.create_batch(
            source="master_seed", source_metadata={"file_name": path.name}
        )
        report = MasterSeedImportReport(batch_id=batch.id)

        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                sku = _clean(row.get("sku"))
                if not sku:
                    continue
                try:
                    self._stage_row(batch.id, row, report)
                except Exception as exc:  # noqa: BLE001 - one bad row must not abort the batch
                    logger.exception("Master seed import: row %s failed", sku)
                    report.errors.append(f"{sku}: {exc}")
                    continue
                report.rows_staged += 1

        self._import_repo.finish_batch(
            batch.id,
            status="completed" if not report.errors else "failed",
            error_summary="; ".join(report.errors[:20]),
        )
        return report

    def _stage_row(
        self, batch_id: uuid.UUID, row: dict[str, str], report: MasterSeedImportReport
    ) -> None:
        sku = _clean(row["sku"])
        record_state = _clean(row.get("record_state"))
        content_status = _clean(row.get("content_status"))
        not_for_sale = record_state == _NOT_FOR_SALE_RECORD_STATE
        if not_for_sale:
            report.not_for_sale_count += 1
        if content_status == "AUTO_DRAFT":
            report.auto_draft_content_count += 1

        music_attributes = {
            key: _clean(row.get(key)) for key in _MUSIC_ATTRIBUTE_COLUMNS if _clean(row.get(key))
        }
        bullet_points = [_clean(row.get(col)) for col in _BULLET_COLUMNS]
        bullet_points = [b for b in bullet_points if b]

        tags = [t.strip() for t in _clean(row.get("tags")).split(",") if t.strip()]
        if not_for_sale:
            tags.append(_NOT_FOR_SALE_TAG)

        vat_percent = _to_decimal(row.get("vat_percent"))
        tax_rate = str(vat_percent / Decimal("100")) if vat_percent is not None else None

        normalized_fields: dict[str, object] = {
            "status": _clean(row.get("status")) or "draft",
            "record_state": record_state,
            "active": _to_bool(row.get("active")),
            "not_for_sale": not_for_sale,
            "brand": _clean(row.get("brand")),
            "category": _clean(row.get("category_primary")),
            "product_type": _clean(row.get("product_type")) or "physical",
            "format": _clean(row.get("format")),
            "title_short": _clean(row.get("title_short")),
            "code_short": _clean(row.get("code_short")),
            "description": _clean(row.get("description")),
            "content_status": content_status,
            "bullet_points": bullet_points,
            "suggested_tags": sorted(set(tags)),
            "brutto": str(row.get("price_gross") or "") or None,
            "netto": str(row.get("price_net") or "") or None,
            "tax_rate": tax_rate,
            "stock_on_hand": _to_int(row.get("stock_on_hand")),
            "stock_enabled": _to_bool(row.get("stock_enabled")),
            "weight_grams": _to_int(row.get("weight_grams")),
            "wix_handle_id": _clean(row.get("wix_handle_id")),
            "wix_visible": _to_bool(row.get("wix_visible")),
            "erp_category": _clean(row.get("erp_category")),
            "music_attributes": music_attributes,
            "parent_sku": _clean(row.get("parent_sku")),
            "product_group_id": _clean(row.get("product_group_id")),
            "group_key": _clean(row.get("group_key")),
            "grouping_confidence": _clean(row.get("grouping_confidence")),
            "conflict_flags": _clean(row.get("conflict_flags")),
            "conflict_notes": _clean(row.get("conflict_notes")),
        }

        staging = self._import_repo.ingest_staging_product(
            import_batch_id=batch_id,
            source="master_seed",
            source_key=sku,
            source_external_id=sku,
            sku=sku,
            name=_clean(row.get("title_full")) or sku,
            raw_payload=dict(row),
            normalized_fields=normalized_fields,
        )

        for column, scheme in _IDENTIFIER_COLUMNS:
            value = _clean(row.get(column))
            if value:
                self._import_repo.add_identifier(
                    staging.id, scheme=scheme, value=value, normalized_value=value.upper()
                )
                report.identifiers_staged += 1

        asin = _clean(row.get("asin"))
        if asin:
            self._import_repo.add_identifier(
                staging.id, scheme="ASIN", value=asin, normalized_value=asin.upper()
            )
            report.identifiers_staged += 1

        fnsku = _clean(row.get("fnsku"))
        if fnsku:
            self._import_repo.add_identifier(
                staging.id, scheme="FNSKU", value=fnsku, normalized_value=fnsku.upper()
            )
            report.identifiers_staged += 1

        category = _clean(row.get("category_primary"))
        if category:
            self._import_repo.add_category(
                staging.id, external_category_id=category, external_category_name=category
            )
