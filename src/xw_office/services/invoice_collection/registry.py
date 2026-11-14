"""Secret-free provider catalog loading and validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ipaddress
import re
from typing import Any

import yaml

from xw_office.services.invoice_collection.errors import (
    InvoiceCollectionError,
    InvoiceErrorCode,
)


@dataclass(frozen=True)
class RouteCapabilities:
    mailbox_probe: bool = False
    protected_credential: bool = False


@dataclass(frozen=True)
class RouteManifest:
    route_key: str
    method: str
    connector: str
    priority: int
    maturity: str
    allowed_hosts: tuple[str, ...] = ()
    auth: str | None = None
    required_scope: str | None = None

    @property
    def capabilities(self) -> RouteCapabilities:
        """Expose supported setup actions from the declared auth mechanism."""
        return RouteCapabilities(
            mailbox_probe=self.auth == "microsoft_graph_mail",
            protected_credential=self.auth == "api_token",
        )


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    label: str
    category: str
    supported_tenants: frozenset[str]
    document_types: frozenset[str]
    routes: tuple[RouteManifest, ...]
    portal_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCatalog:
    schema_version: int
    providers: tuple[ProviderManifest, ...]

    def route(self, provider_id: str, route_key: str) -> RouteManifest | None:
        provider = next((item for item in self.providers if item.provider_id == provider_id), None)
        if provider is None:
            return None
        return next((item for item in provider.routes if item.route_key == route_key), None)

    @classmethod
    def from_yaml(cls, path: Path) -> "ProviderCatalog":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict) or payload.get("schema_version") != 2:
            raise InvoiceCollectionError(
                InvoiceErrorCode.CONFIGURATION_ERROR,
                "Provider-Registry besitzt keine unterstützte schema_version",
            )
        providers = _parse_providers(payload)
        return cls(schema_version=2, providers=tuple(providers))


def _parse_providers(payload: dict[str, Any]) -> list[ProviderManifest]:
    allowed_tenants = set(payload.get("supported_tenants") or ())
    allowed_types = set(payload.get("allowed_document_types") or ())
    allowed_methods = set(payload.get("allowed_route_methods") or ())
    allowed_categories = set(payload.get("allowed_provider_categories") or ())
    providers_payload = payload.get("providers")
    if not isinstance(providers_payload, list):
        raise _configuration_error("providers fehlt oder ist keine Liste")
    seen_providers: set[str] = set()
    manifests: list[ProviderManifest] = []
    for raw in providers_payload:
        if not isinstance(raw, dict):
            raise _configuration_error("Provider-Eintrag ist kein Mapping")
        _assert_secret_free(raw)
        provider_id = _required_string(raw, "id")
        if provider_id in seen_providers:
            raise _configuration_error(f"Provider-ID doppelt: {provider_id}")
        seen_providers.add(provider_id)
        category = _required_string(raw, "category")
        tenants = _string_set(raw.get("supported_tenants"), "supported_tenants")
        types = _string_set(raw.get("document_types"), "document_types")
        if not tenants <= allowed_tenants or not types <= allowed_types:
            raise _configuration_error(f"Provider {provider_id} verwendet unbekannte Werte")
        if category not in allowed_categories:
            raise _configuration_error(f"Provider {provider_id} verwendet unbekannte Kategorie")
        routes = _parse_routes(raw.get("routes") or [], provider_id, allowed_methods)
        portal_hosts = _portal_hosts(raw.get("portal_hosts") or [], provider_id)
        manifests.append(
            ProviderManifest(
                provider_id=provider_id,
                label=_required_string(raw, "label"),
                category=category,
                supported_tenants=frozenset(tenants),
                document_types=frozenset(types),
                routes=tuple(routes),
                portal_hosts=portal_hosts,
            )
        )
    return manifests


def _parse_routes(
    raw_routes: list[Any], provider_id: str, allowed_methods: set[str]
) -> list[RouteManifest]:
    seen: set[str] = set()
    result: list[RouteManifest] = []
    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise _configuration_error(f"Route von {provider_id} ist kein Mapping")
        route_key = _required_string(raw, "id")
        if route_key in seen:
            raise _configuration_error(f"Route-ID doppelt: {provider_id}/{route_key}")
        seen.add(route_key)
        method = _required_string(raw, "method")
        if method not in allowed_methods:
            raise _configuration_error(f"Unbekannte Route-Methode: {method}")
        connector = _required_string(raw, "connector")
        maturity = str(raw.get("maturity") or "planned")
        if maturity not in {"planned", "experimental", "verified", "disabled"}:
            raise _configuration_error(f"Unbekannter Reifegrad: {maturity}")
        if "import" in connector.casefold() or "__" in connector:
            raise _configuration_error("Connector-Namen dürfen keine Importsyntax enthalten")
        hosts = tuple(str(value).strip().lower() for value in raw.get("allowed_hosts") or ())
        if method in {"official_api", "browser"} and not hosts and maturity != "planned":
            raise _configuration_error(
                f"Route {provider_id}/{route_key} besitzt keine Host-Allowlist"
            )
        result.append(
            RouteManifest(
                route_key=route_key,
                method=method,
                connector=connector,
                priority=int(raw.get("priority") or 100),
                maturity=maturity,
                allowed_hosts=hosts,
                auth=str(raw.get("auth") or "").strip() or None,
                required_scope=str(raw.get("required_scope") or "").strip() or None,
            )
        )
    return result


def _required_string(mapping: dict[str, Any], key: str) -> str:
    value = str(mapping.get(key) or "").strip()
    if not value:
        raise _configuration_error(f"Pflichtfeld fehlt: {key}")
    return value


def _portal_hosts(value: Any, provider_id: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _configuration_error(f"portal_hosts von {provider_id} muss eine Liste sein")
    hosts: list[str] = []
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    for raw_host in value:
        host = str(raw_host).strip().casefold()
        if (
            len(host) > 253
            or "." not in host
            or not re.fullmatch(rf"{label}(?:\.{label})+", host)
        ):
            raise _configuration_error(f"Ungueltiger Provider-Portalhost: {provider_id}")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise _configuration_error(f"IP-Adressen sind keine Provider-Portalhosts: {provider_id}")
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _string_set(value: Any, key: str) -> set[str]:
    if not isinstance(value, list):
        raise _configuration_error(f"{key} muss eine Liste sein")
    return {str(item).strip() for item in value if str(item).strip()}


def _configuration_error(message: str) -> InvoiceCollectionError:
    return InvoiceCollectionError(InvoiceErrorCode.CONFIGURATION_ERROR, message)


def _assert_secret_free(value: Any, *, path: str = "provider") -> None:
    """Reject secret-shaped values while allowing declarative policy names."""
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).casefold()
            if any(marker in key_text for marker in ("token", "password", "cookie", "secret")):
                raise _configuration_error(f"Secretwert im Provider-Katalog: {path}.{key}")
            _assert_secret_free(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_secret_free(child, path=f"{path}[{index}]")
