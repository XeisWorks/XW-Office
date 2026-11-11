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


def test_inventory_worker_projects_channels_only_after_master_and_clean_sync(monkeypatch) -> None:
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setenv("XW_PRODUCT_HUB_INVENTORY_MASTER_ENABLED", "true")
    monkeypatch.setattr(inventory_worker_cli, "forecast_main", lambda args: 0)
    monkeypatch.setattr(inventory_worker_cli, "sync_main", lambda args: 0)
    monkeypatch.setattr(
        inventory_worker_cli,
        "projection_main",
        lambda args: calls.append(("projection", list(args))) or 0,
    )

    assert inventory_worker_cli.run_once() == (0, 0)
    assert calls == [("projection", ["--write"])]


def test_inventory_worker_returns_failure_for_failed_cycle(monkeypatch) -> None:
    monkeypatch.setattr(inventory_worker_cli, "run_once", lambda **_kwargs: (0, 1))
    assert inventory_worker_cli.main(["--once"]) == 1


def test_inventory_worker_logs_start_and_cycle_result(monkeypatch, caplog) -> None:
    monkeypatch.setattr(inventory_worker_cli, "run_once", lambda **_kwargs: (0, 0))

    with caplog.at_level("INFO"):
        assert inventory_worker_cli.main(["--once"]) == 0

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("Inventory worker started") for message in messages)
    assert "Inventory cycle finished forecast=0 sync=0" in messages
