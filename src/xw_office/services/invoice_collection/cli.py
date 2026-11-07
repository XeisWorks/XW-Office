"""Operational CLI for local invoice-collection setup and visible browser login."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from xw_office.core.app_paths import default_invoice_target_dir, find_repo_root
from xw_office.services.invoice_collection.domain import TenantId
from xw_office.services.invoice_collection.playwright_session import PlaywrightPersistentSession
from xw_office.services.invoice_collection.registry import ProviderCatalog, ProviderManifest, RouteManifest
from xw_office.services.invoice_collection.security import ensure_invoice_collection_dirs


_SAFE_PART = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_PROVIDER_ORDER = (
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
)


def registry_path() -> Path:
    return find_repo_root() / "markdowns" / "rechnungsautomat_ausgabenpruefung_2026-11" / "PROVIDER_REGISTRY.yaml"


def load_catalog() -> ProviderCatalog:
    return ProviderCatalog.from_yaml(registry_path())


def browser_route(catalog: ProviderCatalog, provider_id: str) -> tuple[ProviderManifest, RouteManifest]:
    provider = next((item for item in catalog.providers if item.provider_id == provider_id), None)
    if provider is None:
        raise ValueError(f"Unbekannter Provider: {provider_id}")
    route = next((item for item in provider.routes if item.method == "browser"), None)
    if route is None or not route.allowed_hosts:
        raise ValueError(f"Provider besitzt keine browser route mit Host-Allowlist: {provider_id}")
    return provider, route


def profile_path(provider_id: str, tenant: str, account_alias: str) -> Path:
    parts = [_SAFE_PART.sub("-", value.strip()).strip(".-") or "unknown" for value in (tenant, provider_id, account_alias)]
    return ensure_invoice_collection_dirs()["profiles"].joinpath(*parts)


def command_doctor(_: argparse.Namespace) -> int:
    catalog = load_catalog()
    browser_count = sum(1 for provider in catalog.providers for route in provider.routes if route.method == "browser")
    playwright_ok = True
    try:
        import playwright  # noqa: F401
    except ImportError:
        playwright_ok = False
    target = default_invoice_target_dir()
    print(f"registry={registry_path()}")
    print(f"browser_routes={browser_count}")
    print(f"playwright={'ok' if playwright_ok else 'missing'}")
    print(f"chromium_target={target}")
    print(f"default_target_exists={target.is_dir()}")
    return 0 if playwright_ok else 2


def command_catalog(_: argparse.Namespace) -> int:
    catalog = load_catalog()
    for provider in catalog.providers:
        for route in provider.routes:
            if route.method == "browser":
                print(f"{provider.provider_id}\t{route.connector}\t{','.join(route.allowed_hosts)}")
    return 0


def command_login(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    provider, route = browser_route(catalog, args.provider)
    if args.tenant not in {tenant.value for tenant in TenantId}:
        raise ValueError(f"Unbekannter Mandant: {args.tenant}")
    profile = profile_path(provider.provider_id, args.tenant, args.account_alias)
    host = route.allowed_hosts[0]
    login_url = f"https://{host}/"
    session = PlaywrightPersistentSession(
        profile_dir=profile,
        login_url=login_url,
        probe_url=login_url,
        allowed_hosts=frozenset(route.allowed_hosts),
        probe_callback=lambda page: True,
        discover_callback=lambda page: [],
        download_callback=lambda page, candidate, destination: None,
    )
    try:
        session.open_login()
        print(f"Sichtbarer Login geÃ¶ffnet: {provider.provider_id} ({route.connector})")
        print("Nach Login/2FA Enter drÃ¼cken; keine Zugangsdaten im Chat oder Terminal eingeben.")
        input()
    finally:
        session.close()
    return 0


def _login_progress_path() -> Path:
    return ensure_invoice_collection_dirs()["journal"] / "browser_login_progress.json"


def _write_login_progress(entries: list[dict[str, str]]) -> None:
    path = _login_progress_path()
    path.write_text(json.dumps(entries, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def command_login_all(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    providers = list(args.providers or _DEFAULT_PROVIDER_ORDER)
    entries: list[dict[str, str]] = []
    for index, provider_id in enumerate(providers, start=1):
        provider, route = browser_route(catalog, provider_id)
        profile = profile_path(provider.provider_id, args.tenant, args.account_alias)
        host = route.allowed_hosts[0]
        login_url = f"https://{host}/"
        session = PlaywrightPersistentSession(
            profile_dir=profile,
            login_url=login_url,
            probe_url=login_url,
            allowed_hosts=frozenset(route.allowed_hosts),
            probe_callback=lambda page: True,
            discover_callback=lambda page: [],
            download_callback=lambda page, candidate, destination: None,
        )
        status = "skipped"
        try:
            session.open_login()
            print(f"[{index}/{len(providers)}] {provider.provider_id}: visible login opened")
            print("Enter=login completed, s=skip (for example rejected Google login), q=stop queue")
            try:
                action = input().strip().casefold()
            except EOFError:
                action = "s"
            if action == "q":
                status = "stopped"
            elif action in {"", "enter", "done", "erledigt", "ok"}:
                status = "authenticated_pending_probe"
            else:
                status = "auth_required_or_skipped"
        except Exception as exc:  # noqa: BLE001 - continue independently per portal
            status = f"setup_error:{type(exc).__name__}"
            print(f"[{index}/{len(providers)}] {provider.provider_id}: {status}", file=sys.stderr)
        finally:
            session.close()
        entries.append(
            {
                "provider_id": provider.provider_id,
                "connector": route.connector,
                "status": status,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_login_progress(entries)
        if status == "stopped":
            break
    print(f"Login queue progress: {_login_progress_path()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="xw-invoice-collection")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="validate local runtime and registry")
    doctor.set_defaults(handler=command_doctor)
    catalog = subparsers.add_parser("catalog", help="list registry browser routes")
    catalog.set_defaults(handler=command_catalog)
    login = subparsers.add_parser("login", help="open one visible persistent browser login")
    login.add_argument("--provider", required=True)
    login.add_argument("--tenant", default=TenantId.XW.value, choices=[tenant.value for tenant in TenantId])
    login.add_argument("--account-alias", default="primary")
    login.set_defaults(handler=command_login)
    login_all = subparsers.add_parser("login-all", help="open all visible logins sequentially")
    login_all.add_argument("--tenant", default=TenantId.XW.value, choices=[tenant.value for tenant in TenantId])
    login_all.add_argument("--account-alias", default="primary")
    login_all.add_argument("--providers", nargs="*", help="optional provider order override")
    login_all.set_defaults(handler=command_login_all)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits actionable setup errors
        print(f"invoice-collection: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
