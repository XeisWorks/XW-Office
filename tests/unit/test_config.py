"""Tests for configuration loading."""

from xw_office.core.config import AppConfig, load_config


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


def test_load_config_with_missing_file() -> None:
    config = load_config("nonexistent.yaml")
    assert config.app.name == "XeisWorks Office"


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
    assert config.customer_aftercare.enabled is True
    assert config.customer_aftercare.courtesy.product_discount_percent == 30
    assert config.customer_aftercare.courtesy.shipping_discount_percent == 100
    assert config.customer_aftercare.b2b.max_wait_days == 20


def test_product_print_profiles_use_pdf_xchange_native_backend() -> None:
    config = load_config("config/default.yaml")
    profiles = {profile.id: profile for profile in config.printing.all_profiles()}

    expected_printers = {
        "noten_simplex": "Noten A4 Simplex",
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
    assert profiles["noten_a5"].rotate_degrees == 90
    assert profiles["noten_a5"].normalize_page_size == "A5"
    assert profiles["noten_a5"].max_upscale_percent == 105.0


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
