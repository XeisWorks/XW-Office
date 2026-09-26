import pytest

from xw_office.services.product_hub.onedrive import OneDriveAssetClient, OneDriveConfigurationError


def test_onedrive_client_fails_closed_without_server_credentials() -> None:
    with pytest.raises(OneDriveConfigurationError):
        OneDriveAssetClient(tenant_id="", client_id="", client_secret="", root_item_id="")
