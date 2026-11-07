from __future__ import annotations

from pathlib import Path

from xw_office.services.invoice_collection.cli import browser_route, load_catalog, profile_path


def test_cli_catalog_contains_all_browser_routes() -> None:
    catalog = load_catalog()
    providers = {
        provider.provider_id
        for provider in catalog.providers
        for route in provider.routes
        if route.method == "browser"
    }
    assert providers == {
        "railway",
        "browserstack",
        "anthropic_api",
        "anthropic_subscription",
        "stripe_fees",
        "github",
        "perplexity",
        "openai_chatgpt",
        "openai_api",
        "microsoft365",
        "amazon_business",
    }


def test_cli_browser_route_and_profile_are_local_and_allowlisted(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    provider, route = browser_route(load_catalog(), "railway")
    assert provider.provider_id == "railway"
    assert route.connector == "railway_billing_playwright"
    assert route.allowed_hosts == ("railway.com",)
    profile = profile_path("railway", "xw", "primary")
    assert profile.is_relative_to(tmp_path / "localappdata")
