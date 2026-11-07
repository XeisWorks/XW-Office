from __future__ import annotations

from pathlib import Path

from xw_office.services.invoice_collection.cli import (
    _DEFAULT_PROVIDER_ORDER,
    browser_route,
    build_parser,
    load_catalog,
    profile_path,
)
from xw_office.core.app_paths import chrome_user_data_dir


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


def test_cli_login_queue_starts_with_railway_and_contains_all_browser_providers() -> None:
    assert _DEFAULT_PROVIDER_ORDER[0] == "railway"
    assert len(_DEFAULT_PROVIDER_ORDER) == 11
    args = build_parser().parse_args(["login-all"])
    assert args.providers is None


def test_existing_chrome_profile_resolves_below_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    assert chrome_user_data_dir() == tmp_path / "localappdata" / "Google" / "Chrome" / "User Data"
