"""Provision / royalty calculation service."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xw_office.repositories.settings_kv import SettingKvRepository

logger = logging.getLogger(__name__)

_ARTICLES_KEY = "calculation.articles"


@dataclass
class ArticleEntry:
    """One article / product with royalty parameters."""

    title: str = ""
    gross_price: float = 0.0
    vat_pct: float = 10.0
    royalty_pct: float = 0.0
    note: str = ""


@dataclass
class RoyaltyResult:
    """Computed royalty for a single article."""

    gross: float
    net: float
    vat_amount: float
    royalty_amount: float
    vat_pct: float
    royalty_pct: float

    @property
    def net_after_royalty(self) -> float:
        return self.net - self.royalty_amount


def calculate_royalty(gross: float, *, vat_pct: float = 10.0, royalty_pct: float = 0.0) -> RoyaltyResult:
    """Compute net, VAT, and royalty amounts from a gross price."""
    if gross < 0:
        raise ValueError("gross must be >= 0")
    divisor = 1.0 + vat_pct / 100.0
    net = gross / divisor
    vat_amount = gross - net
    royalty_amount = net * (royalty_pct / 100.0)
    return RoyaltyResult(
        gross=gross,
        net=net,
        vat_amount=vat_amount,
        royalty_amount=royalty_amount,
        vat_pct=vat_pct,
        royalty_pct=royalty_pct,
    )


class CalculationService:
    """Print rights, participations, article economics."""

    def __init__(self, settings_repo: SettingKvRepository | None = None) -> None:
        self._repo = settings_repo

    # ------------------------------------------------------------------
    # Article list (from settings JSON)
    # ------------------------------------------------------------------

    def load_articles(self) -> list[ArticleEntry]:
        """Load article list from settings DB (key: calculation.articles).

        Returns an empty list when no repo is wired or key is absent.
        """
        if self._repo is None:
            return []
        try:
            raw = self._repo.get_value_json(_ARTICLES_KEY)
            if not raw:
                return []
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [
                ArticleEntry(
                    title=str(item.get("title", "")),
                    gross_price=float(item.get("gross_price", 0.0)),
                    vat_pct=float(item.get("vat_pct", 10.0)),
                    royalty_pct=float(item.get("royalty_pct", 0.0)),
                    note=str(item.get("note", "")),
                )
                for item in data
                if isinstance(item, dict)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("CalculationService.load_articles failed: %s", exc)
            return []

    def save_articles(self, articles: list[ArticleEntry]) -> None:
        """Persist article list to settings DB."""
        if self._repo is None:
            return
        data = [
            {
                "title": a.title,
                "gross_price": a.gross_price,
                "vat_pct": a.vat_pct,
                "royalty_pct": a.royalty_pct,
                "note": a.note,
            }
            for a in articles
        ]
        self._repo.set_value_json(_ARTICLES_KEY, json.dumps(data, ensure_ascii=False))

    def calculate_for_article(self, article: ArticleEntry) -> RoyaltyResult:
        return calculate_royalty(
            article.gross_price,
            vat_pct=article.vat_pct,
            royalty_pct=article.royalty_pct,
        )

    def describe(self) -> str:
        return "Provisionen und Kalkulation: Druckrechte, Beteiligungen, Artikelanalyse."
