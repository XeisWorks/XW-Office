"""Read-only sevDesk TaxSet lookup for Lieferkorrektur invoices (spec §10).

Never creates or modifies a TaxSet — TaxSets are configured in the sevDesk
account itself; this client only matches the country -> text mapping from
:mod:`tax_policy` against what actually exists there (GET /TaxSet).
"""
from __future__ import annotations

from dataclasses import dataclass
import logging

from xw_office.services.http_client import SevdeskConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SevdeskTaxSet:
    id: str
    object_name: str
    text: str


class TaxSetClient:
    """Read-only lookup of live sevDesk TaxSets by text."""

    def __init__(self, connection: SevdeskConnection) -> None:
        self._conn = connection
        self._cache: list[SevdeskTaxSet] = []

    def list_tax_sets(self, *, refresh_cache: bool = False) -> list[SevdeskTaxSet]:
        if not refresh_cache and self._cache:
            return list(self._cache)
        rows = self._fetch_tax_sets()
        self._cache = list(rows)
        return rows

    def find_by_text(self, text: str, *, refresh_cache: bool = False) -> SevdeskTaxSet | None:
        wanted = str(text or "").strip()
        if not wanted:
            return None
        for tax_set in self.list_tax_sets(refresh_cache=refresh_cache):
            if tax_set.text == wanted:
                return tax_set
        return None

    def _fetch_tax_sets(self) -> list[SevdeskTaxSet]:
        try:
            response = self._conn.get("/TaxSet")
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TaxSetClient.list_tax_sets failed: %s", exc)
            return []
        objects = payload.get("objects") if isinstance(payload, dict) else None
        if not isinstance(objects, list):
            return []
        rows: list[SevdeskTaxSet] = []
        for raw in objects:
            if not isinstance(raw, dict):
                continue
            tax_set_id = str(raw.get("id") or "").strip()
            text = str(raw.get("text") or "").strip()
            if tax_set_id and text:
                rows.append(
                    SevdeskTaxSet(
                        id=tax_set_id, object_name=str(raw.get("objectName") or "TaxSet"), text=text
                    )
                )
        return rows
