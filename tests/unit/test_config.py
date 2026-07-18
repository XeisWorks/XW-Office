"""Tests for configuration loading."""
from xw_studio.core.config import AppConfig, load_config


def test_default_config_values() -> None:
    config = AppConfig()
    assert config.app.name == "XeisWorks Studio"
    assert config.app.theme == "dark_teal"
    assert config.printing.music_dpi == 600
    assert config.printing.invoice_dpi == 300
    assert config.printing.buffer_quantity == 3
    assert config.printing.configured_printer_names == []
    assert config.sevdesk.http_max_retries == 3
    assert config.sevdesk.http_retry_backoff_seconds == 0.75
    assert config.crm.fuzzy_match_threshold == 75


def test_load_config_with_missing_file() -> None:
    config = load_config("nonexistent.yaml")
    assert config.app.name == "XeisWorks Studio"


def test_product_print_profiles_use_pdf_xchange_native_backend() -> None:
    config = load_config("config/default.yaml")
    profiles = {
        profile.id: profile
        for profile in config.printing.all_profiles()
    }

    expected_printers = {
        "noten_simplex": "Noten A4 Simplex",
        "noten_duplex": "Noten A4 Duplex",
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
