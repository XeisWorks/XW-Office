"""Read-only audit of the inventory sources used during the Hub transition.

The audit deliberately accepts a normalized row snapshot instead of opening a
database or calling sevDesk itself.  Callers can therefore collect data in their
own worker and pass one consistent snapshot to this pure calculation.  It never
changes legacy settings, Hub rows, or external channel data.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from collections import Counter


ARTICLE_KINDS = frozenset({"external_print", "pod", "digital"})
PHYSICAL_KINDS = frozenset({"external_print", "pod"})


@dataclass(frozen=True)
class InventoryAuditRow:
    """One normalized product/variant row from all available sources."""

    sku: str
    title: str = ""
    article_kind: str = "external_print"
    active: bool = True
    sevdesk_part_id: str = ""
    legacy_on_hand: int | None = None
    hub_on_hand: int | None = None
    sellable_since: dt.date | None = None

    @property
    def normalized_sku(self) -> str:
        return str(self.sku or "").strip().upper()

    @property
    def is_physical(self) -> bool:
        return self.article_kind in PHYSICAL_KINDS


@dataclass(frozen=True)
class InventoryAuditIssue:
    code: str
    severity: str
    sku: str
    title: str
    detail: str


@dataclass(frozen=True)
class InventoryAuditReport:
    rows: tuple[InventoryAuditRow, ...]
    issues: tuple[InventoryAuditIssue, ...]
    active_physical_count: int
    mapped_physical_count: int
    legacy_hub_drift_count: int
    missing_sellable_since_count: int

    @property
    def blocking_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "blocker")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def ready_for_inventory(self) -> bool:
        return self.blocking_issue_count == 0

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-friendly report for a future API or export worker."""
        return {
            "active_physical_count": self.active_physical_count,
            "mapped_physical_count": self.mapped_physical_count,
            "legacy_hub_drift_count": self.legacy_hub_drift_count,
            "missing_sellable_since_count": self.missing_sellable_since_count,
            "blocking_issue_count": self.blocking_issue_count,
            "warning_count": self.warning_count,
            "ready_for_inventory": self.ready_for_inventory,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "sku": issue.sku,
                    "title": issue.title,
                    "detail": issue.detail,
                }
                for issue in self.issues
            ],
        }


def audit_inventory_sources(rows: list[InventoryAuditRow] | tuple[InventoryAuditRow, ...]) -> InventoryAuditReport:
    """Check mapping and source consistency without performing any writes.

    Duplicate SKUs, invalid article kinds and missing sevDesk mappings on active
    physical products block the inventory.  Missing source quantities and missing
    ``sellable_since`` are warnings because the row can still be reviewed manually.
    A legacy/Hub quantity difference is a warning during Shadow mode and is counted
    separately for the Cutover readiness report.
    """
    normalized_rows = tuple(rows)
    issues: list[InventoryAuditIssue] = []
    sku_counts = Counter(row.normalized_sku for row in normalized_rows if row.normalized_sku)

    for row in normalized_rows:
        sku = row.normalized_sku
        title = str(row.title or "").strip()
        if not sku:
            issues.append(
                InventoryAuditIssue("missing_sku", "blocker", "", title, "SKU fehlt.")
            )
            continue
        if sku_counts[sku] > 1:
            issues.append(
                InventoryAuditIssue(
                    "duplicate_sku",
                    "blocker",
                    sku,
                    title,
                    "SKU ist mehrfach im Varianten-Snapshot vorhanden.",
                )
            )
        if row.article_kind not in ARTICLE_KINDS:
            issues.append(
                InventoryAuditIssue(
                    "unknown_article_kind",
                    "blocker",
                    sku,
                    title,
                    f"Unbekannte Artikelart: {row.article_kind!r}.",
                )
            )
        if not row.is_physical:
            continue
        if row.active and not str(row.sevdesk_part_id or "").strip():
            issues.append(
                InventoryAuditIssue(
                    "missing_sevdesk_mapping",
                    "blocker",
                    sku,
                    title,
                    "Aktive physische Variante hat keine sevDesk-Part-Zuordnung.",
                )
            )
        if row.legacy_on_hand is None or row.hub_on_hand is None:
            issues.append(
                InventoryAuditIssue(
                    "missing_source_quantity",
                    "warning",
                    sku,
                    title,
                    "Legacy- oder Hub-Bestand fehlt im Snapshot.",
                )
            )
        elif row.legacy_on_hand < 0 or row.hub_on_hand < 0:
            issues.append(
                InventoryAuditIssue(
                    "negative_source_quantity",
                    "blocker",
                    sku,
                    title,
                    "Eine Bestandsquelle enthält einen negativen Wert.",
                )
            )
        elif row.legacy_on_hand != row.hub_on_hand:
            issues.append(
                InventoryAuditIssue(
                    "legacy_hub_drift",
                    "warning",
                    sku,
                    title,
                    f"Legacy={row.legacy_on_hand}, Hub={row.hub_on_hand}.",
                )
            )
        if row.sellable_since is None:
            issues.append(
                InventoryAuditIssue(
                    "missing_sellable_since",
                    "warning",
                    sku,
                    title,
                    "Beginn der Verkaufbarkeit fehlt; Forecast-Startwert bleibt aktiv.",
                )
            )

    active_physical = sum(1 for row in normalized_rows if row.active and row.is_physical)
    mapped_physical = sum(
        1 for row in normalized_rows if row.active and row.is_physical and row.sevdesk_part_id.strip()
    )
    drift_count = sum(1 for issue in issues if issue.code == "legacy_hub_drift")
    missing_sellable_count = sum(1 for issue in issues if issue.code == "missing_sellable_since")
    return InventoryAuditReport(
        rows=normalized_rows,
        issues=tuple(issues),
        active_physical_count=active_physical,
        mapped_physical_count=mapped_physical,
        legacy_hub_drift_count=drift_count,
        missing_sellable_since_count=missing_sellable_count,
    )


__all__ = [
    "ARTICLE_KINDS",
    "PHYSICAL_KINDS",
    "InventoryAuditIssue",
    "InventoryAuditReport",
    "InventoryAuditRow",
    "audit_inventory_sources",
]
