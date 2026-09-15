"""Aggregate successfully printed PLC labels into compact reporting periods."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from xw_office.repositories.plc_shipment import PlcPrintedShipment, PlcShipmentRepository
from xw_office.services.plc.historical_statistics import (
    PlcHistoricalStatisticsRow,
    historical_statistics_rows,
)
from xw_office.services.shipping.countries import country_name_en

_VIENNA = ZoneInfo("Europe/Vienna")
_UTC = datetime.timezone.utc


@dataclass(frozen=True)
class PlcCountryStatistics:
    country_iso2: str
    country_name: str
    shipment_count: int
    priced_count: int
    weight_kg: Decimal
    price_eur: Decimal


@dataclass(frozen=True)
class PlcPeriodStatistics:
    key: str
    label: str
    date_range: str
    shipment_count: int
    priced_count: int
    weight_kg: Decimal
    price_eur: Decimal
    countries: tuple[PlcCountryStatistics, ...]


class PlcStatisticsService:
    def __init__(self, repository: PlcShipmentRepository | None) -> None:
        self._repository = repository

    @property
    def available(self) -> bool:
        return True

    def load(self, *, now: datetime.datetime | None = None) -> tuple[PlcPeriodStatistics, ...]:
        local_now = self._local_now(now)
        historical_rows = historical_statistics_rows()
        history_start = min(self._as_local(row.printed_at) for row in historical_rows)
        history_end = max(self._as_local(row.printed_at) for row in historical_rows)
        local_start = (history_end + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        starts = {
            "week": (local_now - datetime.timedelta(days=local_now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            "month": local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            "year": local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
            "all": history_start,
        }
        rows: list[PlcPrintedShipment | PlcHistoricalStatisticsRow] = list(historical_rows)
        if self._repository is not None:
            rows.extend(self._repository.list_printed_since(local_start.astimezone(_UTC)))
        definitions = (
            ("week", "Woche", starts["week"]),
            ("month", "Monat", starts["month"]),
            ("year", "Jahr", starts["year"]),
            ("all", "Gesamt", starts["all"]),
        )
        return tuple(
            self._aggregate(key, label, start, local_now, rows)
            for key, label, start in definitions
        )

    @staticmethod
    def _local_now(value: datetime.datetime | None) -> datetime.datetime:
        if value is None:
            return datetime.datetime.now(_VIENNA)
        if value.tzinfo is None:
            return value.replace(tzinfo=_VIENNA)
        return value.astimezone(_VIENNA)

    @staticmethod
    def _as_local(value: datetime.datetime) -> datetime.datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=_UTC)
        return value.astimezone(_VIENNA)

    def _aggregate(
        self,
        key: str,
        label: str,
        start: datetime.datetime,
        end: datetime.datetime,
        rows: list[PlcPrintedShipment | PlcHistoricalStatisticsRow],
    ) -> PlcPeriodStatistics:
        selected = [row for row in rows if start <= self._as_local(row.printed_at) <= end]
        country_rows: dict[str, list[PlcPrintedShipment | PlcHistoricalStatisticsRow]] = {}
        for row in selected:
            country_rows.setdefault(row.country_iso2.upper() or "—", []).append(row)

        countries = tuple(
            PlcCountryStatistics(
                country_iso2=country,
                country_name=country_name_en(country) or country,
                shipment_count=sum(item.shipment_count for item in items),
                priced_count=sum(item.shipment_count for item in items if item.price_eur is not None),
                weight_kg=sum((item.weight_kg or Decimal("0") for item in items), Decimal("0")),
                price_eur=sum(
                    (item.price_eur for item in items if item.price_eur is not None),
                    Decimal("0"),
                ),
            )
            for country, items in sorted(
                country_rows.items(),
                key=lambda item: (
                    -sum(row.shipment_count for row in item[1]),
                    country_name_en(item[0]).casefold(),
                ),
            )
        )
        return PlcPeriodStatistics(
            key=key,
            label=label,
            date_range=f"{start:%d.%m.%Y} – {end:%d.%m.%Y}",
            shipment_count=sum(row.shipment_count for row in selected),
            priced_count=sum(row.shipment_count for row in selected if row.price_eur is not None),
            weight_kg=sum((row.weight_kg or Decimal("0") for row in selected), Decimal("0")),
            price_eur=sum(
                (row.price_eur for row in selected if row.price_eur is not None),
                Decimal("0"),
            ),
            countries=countries,
        )
