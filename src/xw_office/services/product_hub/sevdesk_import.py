"""sevdesk -> Product Hub staging importer (PR04).

Reads sevDesk Parts via the existing ``PartClient`` and writes them into staging
tables (``models/product_hub_import.py``) for later review/matching. **Never writes
to sevdesk** and never touches a canonical product-hub table directly — committing
staged rows is a separate, explicit step (PR06).

Internal-comment rule (build-plan PR04): a Part's ``internalComment`` is kept for
provenance/review only, in ``normalized_fields``. It is never mapped onto a public
description field.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from xw_office.repositories.product_hub_import import ProductHubImportRepository
from xw_office.services.sevdesk.part_client import _parse_part

logger = logging.getLogger(__name__)

_SEVDESK_LOCATION_KEY = "sevdesk"


class SevdeskPartsSource(Protocol):
    """Structural interface satisfied by :class:`~xw_office.services.sevdesk.part_client.PartClient`."""

    def fetch_parts_raw(self, *, max_pages: int = 20) -> list[dict[str, Any]]: ...


@dataclass
class SevdeskImportReport:
    """Outcome of one :meth:`SevdeskPartImporter.run` call."""

    batch_id: uuid.UUID
    parts_seen: int = 0
    parts_staged: int = 0
    categories_staged: int = 0
    errors: list[str] = field(default_factory=list)


class SevdeskPartImporter:
    """Read-only sevdesk Part -> staging importer. Never calls a sevdesk write endpoint."""

    def __init__(
        self,
        *,
        parts_client: SevdeskPartsSource,
        import_repo: ProductHubImportRepository,
        max_pages: int = 20,
    ) -> None:
        self._parts_client = parts_client
        self._import_repo = import_repo
        self._max_pages = max_pages

    def run(self) -> SevdeskImportReport:
        """Import every sevdesk Part into a fresh staging batch."""
        batch = self._import_repo.create_batch(source="sevdesk")
        report = SevdeskImportReport(batch_id=batch.id)

        raw_parts = self._parts_client.fetch_parts_raw(max_pages=self._max_pages)
        report.parts_seen = len(raw_parts)

        for raw in raw_parts:
            part_id = str(raw.get("id") or "").strip()
            if not part_id:
                continue
            try:
                staged_category = self._import_one_part(batch.id, raw)
            except Exception as exc:  # noqa: BLE001 - one bad part must not abort the batch
                logger.exception("sevdesk import: part %s failed", part_id)
                report.errors.append(f"{part_id}: {exc}")
                continue
            report.parts_staged += 1
            report.categories_staged += staged_category

        self._import_repo.finish_batch(
            batch.id,
            status="completed" if not report.errors else "failed",
            error_summary="; ".join(report.errors[:20]),
        )
        return report

    def _import_one_part(self, batch_id: uuid.UUID, raw: dict[str, Any]) -> int:
        part_id = str(raw.get("id") or "").strip()
        # Reuse the already-tested field parsing from PartClient instead of duplicating
        # it — _parse_part is a pure function, not stateful client behavior, so this
        # does not touch or risk any existing sevdesk integration code path.
        part = _parse_part(raw)

        staging_product = self._import_repo.ingest_staging_product(
            import_batch_id=batch_id,
            source="sevdesk",
            source_key=part_id,
            source_external_id=part_id,
            sku=part.sku,
            name=part.name,
            raw_payload=raw,
            normalized_fields={
                "stock_enabled": part.stock_enabled,
                "tax_rate": part.tax_rate,
                "price_eur": part.price_eur,
                "unity": part.unity,
                "internal_comment": part.internal_comment,
            },
        )

        self._import_repo.add_inventory(
            staging_product.id,
            quantity=part.stock_qty,
            location_external_id=_SEVDESK_LOCATION_KEY,
            stock_enabled=part.stock_enabled,
        )

        if part.category_id:
            self._import_repo.add_category(
                staging_product.id,
                external_category_id=part.category_id,
                external_category_name=part.category_name,
            )
            return 1
        return 0
