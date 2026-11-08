from xw_office.services.product_hub import inventory_worker_cli


def test_inventory_worker_once_runs_forecast_and_sync(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_forecast(args):
        calls.append(("forecast", list(args)))
        return 0

    def fake_sync(args):
        calls.append(("sync", list(args)))
        return 0

    monkeypatch.setattr(inventory_worker_cli, "forecast_main", fake_forecast)
    monkeypatch.setattr(inventory_worker_cli, "sync_main", fake_sync)
    assert inventory_worker_cli.main(["--once", "--forecast-years", "4", "--credit-years", "2"]) == 0
    assert calls == [("forecast", ["--years", "4"]), ("sync", ["--years", "2"])]


def test_inventory_worker_returns_failure_for_failed_cycle(monkeypatch) -> None:
    monkeypatch.setattr(inventory_worker_cli, "run_once", lambda **_kwargs: (0, 1))
    assert inventory_worker_cli.main(["--once"]) == 1
