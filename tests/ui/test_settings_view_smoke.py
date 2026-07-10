"""Smoke tests for SettingsView transfer graph status."""
from __future__ import annotations

from xw_studio.bootstrap import register_default_services
from xw_studio.core.config import AppConfig
from xw_studio.core.container import Container
from xw_studio.core.signals import AppSignals
from xw_studio.services.secrets.service import SecretService
from xw_studio.ui.modules.settings.view import SettingsView


class _FakeSecretService:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get_secret(self, key: str) -> str:
        return self._values.get(key, "")


def _build_container_with_secrets(values: dict[str, str]) -> Container:
    cfg = AppConfig()
    container = Container(cfg)
    container.register(AppSignals, lambda _: AppSignals())
    register_default_services(container)
    container.register(SecretService, lambda _: _FakeSecretService(values))
    return container


def test_settings_transfer_graph_status_green(qtbot: object) -> None:
    container = _build_container_with_secrets(
        {
            "MS_GRAPH_TENANT_ID": "tenant-id",
            "MS_GRAPH_CLIENT_ID": "client-id",
            "MS_GRAPH_TRANSFER_MAILBOX": "transfer@xeisworks.at",
            "MS_GRAPH_MAILBOX": "shop@xeisworks.at",
        }
    )
    view = SettingsView(container)
    qtbot.addWidget(view)

    assert "GRUEN" in view._transfer_graph_status.text()  # noqa: SLF001
    assert "transfer@xeisworks.at" in view._transfer_graph_mailbox.text()  # noqa: SLF001


def test_settings_transfer_graph_status_yellow_on_mailbox_fallback(qtbot: object) -> None:
    container = _build_container_with_secrets(
        {
            "MS_GRAPH_TENANT_ID": "tenant-id",
            "MS_GRAPH_CLIENT_ID": "client-id",
            "MS_GRAPH_TRANSFER_MAILBOX": "",
            "MS_GRAPH_MAILBOX": "shop@xeisworks.at",
        }
    )
    view = SettingsView(container)
    qtbot.addWidget(view)

    assert "GELB" in view._transfer_graph_status.text()  # noqa: SLF001
    assert "Fallback" in view._transfer_graph_status.text()  # noqa: SLF001
