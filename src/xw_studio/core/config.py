"""Unified configuration: YAML defaults + .env secrets."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowConfig:
    width: int = 1600
    height: int = 1000
    remember_geometry: bool = True


@dataclass(frozen=True)
class SidebarConfig:
    default_collapsed: bool = False
    width_expanded: int = 220
    width_collapsed: int = 60


@dataclass(frozen=True)
class AppSection:
    name: str = "XeisWorks Studio"
    theme: str = "dark_teal"
    language: str = "de"
    window: WindowConfig = field(default_factory=WindowConfig)
    sidebar: SidebarConfig = field(default_factory=SidebarConfig)


@dataclass(frozen=True)
class RateLimitConfig:
    requests_per_second: int = 2
    cooldown_seconds: int = 5


@dataclass(frozen=True)
class SevdeskSection:
    """sevDesk REST settings. HTTP retry applies to idempotent GET calls in clients."""

    base_url: str = "https://my.sevdesk.de/api/v1"
    api_token: str = ""
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    cache_ttl_seconds: int = 180
    http_max_retries: int = 3
    http_retry_backoff_seconds: float = 0.75


@dataclass(frozen=True)
class WixSection:
    base_url_v1: str = "https://www.wixapis.com/stores/v1"
    base_url_v3: str = "https://www.wixapis.com/stores/v3"
    api_key: str = ""
    site_id: str = ""
    account_id: str = ""


@dataclass(frozen=True)
class FinanzOnlineSection:
    wsdl_url: str = ""
    operation_name: str = "submitUva"
    session_wsdl_url: str = "https://finanzonline.bmf.gv.at/fonws/ws/sessionService.wsdl"
    upload_wsdl_url: str = "https://finanzonline.bmf.gv.at/fon/ws/fileuploadService.wsdl"
    fastnr: str = ""
    hersteller_id: str = ""
    u30_xsd_path: str = ""
    u13_xsd_path: str = ""
    test_mode: bool = True
    submit_timeout_seconds: int = 30


@dataclass(frozen=True)
class PrintProfile:
    """Named print configuration for a specific printer role."""

    id: str = ""
    label: str = ""
    printer_name: str = ""
    dpi: int | None = None
    placement_mode: str = "paper_origin"
    page_size: str = ""
    orientation: str = ""
    scale_mode: str = "none"
    alignment: str = "top_left"
    x_offset_mm: float = 0.0
    y_offset_mm: float = 0.0
    render_color_mode: str = "auto"
    black_enhancement: str = "auto"
    black_threshold: int = 180
    backend: str = "qt_raster"
    native_pdf_exe: str = ""


@dataclass(frozen=True)
class PrintingSection:
    """Print settings. ``configured_printer_names`` = expected Windows printer names on print PC."""

    music_dpi: int = 600
    invoice_dpi: int = 300
    buffer_quantity: int = 3
    rate_limit_seconds: int = 1
    invoice_printer: str = ""
    label_printer: str = ""
    label_model: str = ""
    label_size: str = ""
    label_template_path: str = ""
    configured_printer_names: list[str] = field(default_factory=list)
    # Named profiles loaded from YAML (list[dict] from YAML → list[PrintProfile] via loader)
    print_profiles: list[dict] = field(default_factory=list)

    @staticmethod
    def _profile_from_entry(entry: dict[str, Any]) -> PrintProfile:
        return PrintProfile(
            id=str(entry.get("id") or ""),
            label=str(entry.get("label") or ""),
            printer_name=str(entry.get("printer_name") or ""),
            dpi=int(entry["dpi"]) if entry.get("dpi") else None,
            placement_mode=str(entry.get("placement_mode") or "paper_origin"),
            page_size=str(entry.get("page_size") or ""),
            orientation=str(entry.get("orientation") or ""),
            scale_mode=str(entry.get("scale_mode") or "none"),
            alignment=str(entry.get("alignment") or "top_left"),
            x_offset_mm=float(entry.get("x_offset_mm") or 0.0),
            y_offset_mm=float(entry.get("y_offset_mm") or 0.0),
            render_color_mode=str(entry.get("render_color_mode") or "auto"),
            black_enhancement=str(entry.get("black_enhancement") or "auto"),
            black_threshold=int(entry.get("black_threshold") or 180),
            backend=str(entry.get("backend") or "qt_raster"),
            native_pdf_exe=str(entry.get("native_pdf_exe") or ""),
        )

    def resolve_profile(self, profile_id: str) -> PrintProfile | None:
        """Return the PrintProfile for *profile_id*, or None if not found."""
        for entry in self.print_profiles:
            if isinstance(entry, dict) and entry.get("id") == profile_id:
                return self._profile_from_entry(entry)
        return None

    def all_profiles(self) -> list[PrintProfile]:
        """Return all configured print profiles as typed objects."""
        result: list[PrintProfile] = []
        for entry in self.print_profiles:
            if isinstance(entry, dict) and entry.get("id"):
                result.append(self._profile_from_entry(entry))
        return result


@dataclass(frozen=True)
class InventorySection:
    alarm_threshold: int = 5
    auto_sync_on_start: bool = True


@dataclass(frozen=True)
class CrmSection:
    fuzzy_match_threshold: int = 75
    duplicate_scan_on_sync: bool = True


@dataclass(frozen=True)
class SkuRulesSection:
    print_prefixes: list[str] = field(default_factory=lambda: ["XW-4", "XW-6", "XW-7"])
    unreleased_prefixes: list[str] = field(default_factory=lambda: ["XW-600"])


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration assembled from YAML + env."""
    app: AppSection = field(default_factory=AppSection)
    sevdesk: SevdeskSection = field(default_factory=SevdeskSection)
    wix: WixSection = field(default_factory=WixSection)
    finanzonline: FinanzOnlineSection = field(default_factory=FinanzOnlineSection)
    printing: PrintingSection = field(default_factory=PrintingSection)
    inventory: InventorySection = field(default_factory=InventorySection)
    crm: CrmSection = field(default_factory=CrmSection)
    sku_rules: SkuRulesSection = field(default_factory=SkuRulesSection)
    database_url: str = ""
    fernet_master_key: str = ""


def _merge_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Recursively build a frozen dataclass from a dict."""
    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in field_types:
            continue
        ft = field_types[key]
        if isinstance(ft, str):
            ft = eval(ft)  # noqa: S307 — resolve forward refs
        if isinstance(value, dict) and hasattr(ft, "__dataclass_fields__"):
            kwargs[key] = _merge_dataclass(ft, value)
        elif isinstance(value, list):
            kwargs[key] = list(value)
        else:
            kwargs[key] = value
    return cls(**kwargs)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML + .env, return frozen AppConfig."""
    load_dotenv()

    if config_path is None:
        root = Path(__file__).resolve().parents[3]
        config_path = root / "config" / "default.yaml"

    yaml_data: dict[str, Any] = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    else:
        logger.warning("Config file not found: %s — using defaults", config_path)

    yaml_data.setdefault("sevdesk", {})["api_token"] = os.getenv("SEVDESK_API_TOKEN", "")
    yaml_data.setdefault("wix", {})["api_key"] = os.getenv("WIX_API_KEY", "")
    yaml_data.setdefault("wix", {})["site_id"] = os.getenv("WIX_SITE_ID", "")
    yaml_data.setdefault("wix", {})["account_id"] = os.getenv("WIX_ACCOUNT_ID", "")
    yaml_data.setdefault("finanzonline", {})["wsdl_url"] = os.getenv(
        "FON_SOAP_WSDL",
        yaml_data.setdefault("finanzonline", {}).get("wsdl_url", ""),
    )
    yaml_data.setdefault("finanzonline", {})["operation_name"] = os.getenv(
        "FON_SOAP_OPERATION",
        yaml_data.setdefault("finanzonline", {}).get("operation_name", "submitUva"),
    )
    yaml_data.setdefault("finanzonline", {})["session_wsdl_url"] = os.getenv(
        "FON_SESSION_WSDL",
        yaml_data.setdefault("finanzonline", {}).get(
            "session_wsdl_url",
            "https://finanzonline.bmf.gv.at/fonws/ws/sessionService.wsdl",
        ),
    )
    yaml_data.setdefault("finanzonline", {})["upload_wsdl_url"] = os.getenv(
        "FON_UPLOAD_WSDL",
        yaml_data.setdefault("finanzonline", {}).get(
            "upload_wsdl_url",
            "https://finanzonline.bmf.gv.at/fon/ws/fileuploadService.wsdl",
        ),
    )
    yaml_data.setdefault("finanzonline", {})["fastnr"] = (
        os.getenv("FINANZONLINE_FASTNR", "")
        or os.getenv("FINANZONLINE_STEUERNUMMER", "")
        or os.getenv("FON_STEUERNUMMER", "")
        or os.getenv("FON_FASTNR", "")
        or yaml_data.setdefault("finanzonline", {}).get("fastnr", "")
    )
    yaml_data.setdefault("finanzonline", {})["hersteller_id"] = (
        os.getenv("FON_HERSTELLER_ID", "")
        or os.getenv("FINANZONLINE_UID", "")
        or yaml_data.setdefault("finanzonline", {}).get("hersteller_id", "")
    )
    yaml_data.setdefault("finanzonline", {})["u30_xsd_path"] = os.getenv(
        "FON_U30_XSD",
        yaml_data.setdefault("finanzonline", {}).get("u30_xsd_path", ""),
    )
    yaml_data.setdefault("finanzonline", {})["u13_xsd_path"] = os.getenv(
        "FON_U13_XSD",
        yaml_data.setdefault("finanzonline", {}).get("u13_xsd_path", ""),
    )
    yaml_data.setdefault("finanzonline", {})["test_mode"] = str(
        os.getenv(
            "FON_SOAP_TEST_MODE",
            str(yaml_data.setdefault("finanzonline", {}).get("test_mode", True)),
        )
    ).strip().lower() in {"1", "true", "yes", "ja", "on"}
    db_url = os.getenv("DATABASE_URL", "").strip()
    db_public_url = os.getenv("DATABASE_PUBLIC_URL", "").strip()
    if db_url and ".railway.internal" in db_url and db_public_url:
        # Local desktop setups cannot resolve Railway internal hostnames.
        yaml_data["database_url"] = db_public_url
    else:
        yaml_data["database_url"] = db_url or db_public_url
    yaml_data["fernet_master_key"] = os.getenv("FERNET_MASTER_KEY", "")

    return _merge_dataclass(AppConfig, yaml_data)
