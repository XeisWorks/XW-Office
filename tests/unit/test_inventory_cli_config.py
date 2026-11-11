from __future__ import annotations

from types import SimpleNamespace

import pytest

from xw_office.services.product_hub import forecast_cli, inventory_sync_cli


@pytest.mark.parametrize("module", [forecast_cli, inventory_sync_cli])
def test_inventory_cli_fails_fast_without_sevdesk_token(monkeypatch, module) -> None:
    monkeypatch.setattr(
        module,
        "load_config",
        lambda: SimpleNamespace(database_url="postgresql://example", sevdesk=SimpleNamespace(api_token="")),
    )

    with pytest.raises(SystemExit) as exc_info:
        module.main([])

    assert exc_info.value.code == 2
