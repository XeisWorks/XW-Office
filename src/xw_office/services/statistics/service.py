"""Revenue / business statistics — aggregated from sevDesk invoices."""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from xw_office.services.sevdesk.invoice_client import InvoiceClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MonthlyRevenue:
    """Gross revenue for one calendar month."""

    year_month: str   # e.g. "2025-11"
    gross_total: float
    invoice_count: int


@dataclass(frozen=True)
class StatsSummary:
    """Top-level KPI snapshot."""

    total_invoices: int
    paid_invoices: int
    open_invoices: int
    total_gross: float
    by_month: list[MonthlyRevenue]
    source: str  # "live" | "mock"


class StatisticsService:
    """Aggregate KPIs from sevDesk invoices (live when InvoiceClient is injected)."""

    def __init__(self, invoice_client: "InvoiceClient | None" = None) -> None:
        self._client = invoice_client

    def has_live_connection(self) -> bool:
        return self._client is not None

    def describe(self) -> str:
        src = "live (sevDesk)" if self.has_live_connection() else "Mock"
        return f"Statistik: Umsatz, Kanaele, Export — Quelle: {src}."

    def load_summary(self, *, max_invoices: int = 500) -> StatsSummary:
        """Build KPI snapshot — pulls from sevDesk or returns mock data."""
        if self._client is None:
            return self._mock_summary()

        try:
            rows = self._client.list_invoice_summaries(limit=max_invoices)
        except Exception:
            logger.exception("StatisticsService: invoice fetch failed — returning mock")
            return self._mock_summary()

        paid = [r for r in rows if r.status_code == 1000]
        open_ = [r for r in rows if r.status_code == 200]

        total_gross = 0.0
        by_month: dict[str, list[float]] = defaultdict(list)
        for inv in rows:
            try:
                gross = float(inv.sum_gross or 0)
            except (TypeError, ValueError):
                gross = 0.0
            total_gross += gross
            date = (inv.invoice_date or "")[:7]  # "YYYY-MM"
            if date:
                by_month[date].append(gross)

        monthly = sorted(
            [
                MonthlyRevenue(
                    year_month=ym,
                    gross_total=round(sum(amounts), 2),
                    invoice_count=len(amounts),
                )
                for ym, amounts in by_month.items()
            ],
            key=lambda x: x.year_month,
        )

        return StatsSummary(
            total_invoices=len(rows),
            paid_invoices=len(paid),
            open_invoices=len(open_),
            total_gross=round(total_gross, 2),
            by_month=monthly,
            source="live",
        )

    # ------------------------------------------------------------------

    def _mock_summary(self) -> StatsSummary:
        return StatsSummary(
            total_invoices=0,
            paid_invoices=0,
            open_invoices=0,
            total_gross=0.0,
            by_month=[],
            source="mock",
        )

    def summary_mock(self) -> dict[str, Any]:
        """Legacy helper kept for backwards compat."""
        return {"hinweis": "Mock-Daten — echte Aggregation via InvoiceClient", "umsatz": "—"}

