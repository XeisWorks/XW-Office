"""Aggregate successfully printed PLC labels into compact reporting periods."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from xw_studio.repositories.plc_shipment import PlcPrintedShipment, PlcShipmentRepository
from xw_studio.services.shipping.countries import country_name_en

_VIENNA = ZoneInfo("Europe/Vienna")
_UTC = datetime.timezone.utc


@dataclass(frozen=True)
class PlcCountryStatistics:
    country_iso2: str
    country_name: str
    shipment_count: int
    priced_count: int
    price_eur: Decimal


@dataclass(frozen=True)
class PlcPeriodStatistics:
    key: str
    label: str
    date_range: str
    shipment_count: int
    priced_count: int
    price_eur: Decimal
    countries: tuple[PlcCountryStatistics, ...]


class PlcStatisticsService:
    def __init__(self, repository: PlcShipmentRepository | None) -> None:
        self._repository = repository

    @property
    def available(self) -> bool:
        return self._repository is not None

    def load(self, *, now: datetime.datetime | None = None) -> tuple[PlcPeriodStatistics, ...]:
        if self._repository is None:
            raise RuntimeError("Railway-Datenbank ist nicht konfiguriert.")
        local_now = self._local_now(now)
        starts = {
            "week": (local_now - datetime.timedelta(days=local_now.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
            "month": local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
            "year": local_now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
        }
        rows = self._repository.list_printed_since(starts["year"].astimezone(_UTC))
        definitions = (
            ("week", "Woche", starts["week"]),
            ("month", "Monat", starts["month"]),
            ("year", "Jahr", starts["year"]),
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
        rows: list[PlcPrintedShipment],
    ) -> PlcPeriodStatistics:
        selected = [row for row in rows if start <= self._as_local(row.printed_at) <= end]
        country_rows: dict[str, list[PlcPrintedShipment]] = {}
        for row in selected:
            country_rows.setdefault(row.country_iso2.upper() or "—", []).append(row)

        countries = tuple(
            PlcCountryStatistics(
                country_iso2=country,
                country_name=country_name_en(country) or country,
                shipment_count=len(items),
                priced_count=sum(item.price_eur is not None for item in items),
                price_eur=sum(
                    (item.price_eur for item in items if item.price_eur is not None),
                    Decimal("0"),
                ),
            )
            for country, items in sorted(
                country_rows.items(),
                key=lambda item: (-(len(item[1])), country_name_en(item[0]).casefold()),
            )
        )
        return PlcPeriodStatistics(
            key=key,
            label=label,
            date_range=f"{start:%d.%m.%Y} – {end:%d.%m.%Y}",
            shipment_count=len(selected),
            priced_count=sum(row.price_eur is not None for row in selected),
            price_eur=sum(
                (row.price_eur for row in selected if row.price_eur is not None),
                Decimal("0"),
            ),
            countries=countries,
        )
