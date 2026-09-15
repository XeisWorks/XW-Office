import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from xw_office.services.plc.historical_statistics import historical_statistics_rows
from xw_office.services.plc.statistics import PlcStatisticsService


def test_historical_post_export_is_sanitised_and_complete() -> None:
    rows = historical_statistics_rows()

    assert len(rows) == 184
    assert sum(row.shipment_count for row in rows) == 258
    assert sum(row.weight_kg for row in rows) == Decimal("1113.88")
    assert sum(row.price_eur for row in rows) == Decimal("2623.14")
    assert {row.country_iso2 for row in rows} == {"AT", "CH", "CZ", "DE", "IT", "LI", "NL"}


def test_statistics_exposes_historical_export_without_database() -> None:
    now = datetime.datetime(2026, 9, 15, 23, 59, tzinfo=ZoneInfo("Europe/Vienna"))

    statistics = PlcStatisticsService(None).load(now=now)
    total = next(period for period in statistics if period.key == "all")

    assert [period.key for period in statistics] == ["week", "month", "year", "all"]
    assert total.shipment_count == 258
    assert total.priced_count == 258
    assert total.weight_kg == Decimal("1113.88")
    assert total.price_eur == Decimal("2623.14")
    germany = next(country for country in total.countries if country.country_iso2 == "DE")
    assert germany.shipment_count == 129
    assert germany.weight_kg == Decimal("512.26")
    assert germany.price_eur == Decimal("1443.66")


def test_local_rows_start_after_the_historical_export_to_avoid_duplicates() -> None:
    class RecordingRepository:
        since: datetime.datetime | None = None

        def list_printed_since(self, since: datetime.datetime) -> list[object]:
            self.since = since
            return []

    repository = RecordingRepository()
    now = datetime.datetime(2026, 9, 16, 12, tzinfo=ZoneInfo("Europe/Vienna"))

    PlcStatisticsService(repository).load(now=now)  # type: ignore[arg-type]

    assert repository.since == datetime.datetime(2026, 9, 15, 22, tzinfo=datetime.timezone.utc)
