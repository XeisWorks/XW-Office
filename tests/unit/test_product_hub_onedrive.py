import pytest

from xw_office.services.product_hub.onedrive import OneDriveAssetClient, OneDriveConfigurationError


def test_onedrive_client_fails_closed_without_server_credentials() -> None:
    with pytest.raises(OneDriveConfigurationError):
        OneDriveAssetClient(tenant_id="", client_id="", client_secret="", root_item_id="")


def test_onedrive_client_requires_stable_drive_item_root(monkeypatch) -> None:
    with pytest.raises(OneDriveConfigurationError):
        OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="path-only")
    monkeypatch.setattr("xw_office.services.product_hub.onedrive.msal.ConfidentialClientApplication", lambda *args, **kwargs: object())
    client = OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="drive:item")
    assert (client.root_drive_id, client.root_item_id) == ("drive", "item")
