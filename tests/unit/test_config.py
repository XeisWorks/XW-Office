"""Tests for configuration loading."""

from pathlib import Path

import pytest

from xw_office.core.config import AppConfig, load_config
from xw_office.core import config as config_module


def test_default_config_values() -> None:
    config = AppConfig()
    assert config.app.name == "XeisWorks Office"
    assert config.app.theme == "dark_gold"
    assert config.printing.music_dpi == 600
    assert config.printing.invoice_dpi == 300
    assert config.printing.buffer_quantity == 3
    assert config.printing.configured_printer_names == []
    assert config.sevdesk.http_max_retries == 3
    assert config.sevdesk.http_retry_backoff_seconds == 0.75
    assert config.crm.fuzzy_match_threshold == 75
    assert config.inventory.start_stock_booking_enabled is False


def test_load_config_with_missing_file() -> None:
    config = load_config("nonexistent.yaml")
    assert config.app.name == "XeisWorks Office"


def test_load_config_does_not_read_local_env_under_doppler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOPPLER_PROJECT", "xw-office-desktop")
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda: pytest.fail("local .env must not be read under Doppler"),
    )

    assert load_config("nonexistent.yaml").app.name == "XeisWorks Office"


@pytest.mark.parametrize("yaml_content", ["[]", "true", "'scalar'"])
def test_load_config_rejects_non_mapping_yaml_root(
    tmp_path: Path,
    yaml_content: str,
) -> None:
    config_path = tmp_path / "invalid-root.yaml"
    config_path.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ValueError, match="YAML object at its root"):
        load_config(config_path)


def test_start_stock_booking_can_be_enabled_in_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "stock-enabled.yaml"
    config_path.write_text("inventory:\n  start_stock_booking_enabled: true\n", encoding="utf-8")

    assert load_config(config_path).inventory.start_stock_booking_enabled is True


def test_product_hub_runtime_flags_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XW_PRODUCT_HUB_SYNC_PUSH_ENABLED", "true")
    monkeypatch.setenv("XW_PRODUCT_HUB_INVENTORY_SHADOW_ENABLED", "yes")
    monkeypatch.setenv("XW_PRODUCT_HUB_INVENTORY_MASTER_ENABLED", "on")

    config = load_config("nonexistent.yaml")

    assert config.product_hub.sync_push_enabled is True
    assert config.product_hub.inventory_shadow_enabled is True
    assert config.product_hub.inventory_master_enabled is True


def test_customer_aftercare_defaults() -> None:
    config = AppConfig()
    assert config.customer_aftercare.enabled is True
    assert config.customer_aftercare.ai.enabled is True
    assert config.customer_aftercare.ai.min_confidence_for_prefill == 0.75
    assert config.customer_aftercare.b2b.wait_for_next_order is True
    assert config.customer_aftercare.b2b.max_wait_days == 20
    assert config.customer_aftercare.courtesy.default_enabled is True
    assert config.customer_aftercare.courtesy.product_discount_percent == 30
    assert config.customer_aftercare.courtesy.shipping_discount_percent == 100
    assert config.customer_aftercare.polling.inbox_seconds == 300
    assert config.customer_aftercare.polling.due_check_seconds == 60
    assert config.customer_aftercare.polling.wix_order_check_seconds == 60


def test_customer_aftercare_loaded_from_yaml() -> None:
    config = load_config("config/default.yaml")
    assert config.inventory.start_stock_booking_enabled is False
    assert config.customer_aftercare.enabled is True
    assert config.customer_aftercare.courtesy.product_discount_percent == 30
    assert config.customer_aftercare.courtesy.shipping_discount_percent == 100
    assert config.customer_aftercare.b2b.max_wait_days == 20


def test_product_print_profiles_use_pdf_xchange_native_backend() -> None:
    config = load_config("config/default.yaml")
    profiles = {profile.id: profile for profile in config.printing.all_profiles()}

    expected_printers = {
        "noten_simplex": "Noten A4 Simplex",
        "noten_simplex_color": "Noten A4 Simplex Color",
        "noten_duplex": "Noten A4 Duplex",
        "noten_a5": "Noten A5",
        "brochure_mono": "Canon Broschüre Mono",
        "brochure_duo": "Canon Broschüre Duo",
    }
    assert "noten_native_pilot" not in profiles
    for profile_id, printer_name in expected_printers.items():
        profile = profiles[profile_id]
        assert profile.label == printer_name
        assert profile.printer_name == printer_name
        assert profile.backend == "pdf_xchange"
        assert profile.native_pdf_exe.endswith("PXCEditor.exe")
    assert profiles["noten_a5"].rotate_degrees == 0
    assert profiles["noten_a5"].orientation == "landscape"
    assert profiles["noten_a5"].normalize_page_size == "A5"
    assert profiles["noten_a5"].max_upscale_percent == 110.0


def test_plc_customs_profile_uses_dedicated_unscaled_af_printer() -> None:
    config = load_config("config/default.yaml")

    profile = config.printing.resolve_profile("plc_customs")

    assert profile is not None
    assert profile.printer_name == "Zollformular XW 100"
    assert profile.page_size == "A5"
    assert profile.placement_mode == "paper_origin"
    assert profile.scale_mode == "fit"
    assert profile.scale_percent == 100.0
    assert profile.alignment == "top_left"
    assert "Zollformular XW 100" in config.printing.configured_printer_names
