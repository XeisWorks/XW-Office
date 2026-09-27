import pytest

from xw_office.services.product_hub.onedrive import OneDriveAssetClient, OneDriveConfigurationError, OneDriveItem


def test_onedrive_client_fails_closed_without_server_credentials() -> None:
    with pytest.raises(OneDriveConfigurationError):
        OneDriveAssetClient(tenant_id="", client_id="", client_secret="", root_item_id="")


def test_onedrive_client_requires_stable_drive_item_root(monkeypatch) -> None:
    with pytest.raises(OneDriveConfigurationError):
        OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="path-only")
    monkeypatch.setattr("xw_office.services.product_hub.onedrive.msal.ConfidentialClientApplication", lambda *args, **kwargs: object())
    client = OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="drive:item")
    assert (client.root_drive_id, client.root_item_id) == ("drive", "item")


def test_onedrive_client_only_accepts_items_below_configured_root(monkeypatch) -> None:
    monkeypatch.setattr("xw_office.services.product_hub.onedrive.msal.ConfidentialClientApplication", lambda *args, **kwargs: object())
    client = OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="drive:root")
    parents = {
        "file": OneDriveItem("drive", "file", "score.pdf", "etag", 1, parent_id="folder"),
        "folder": OneDriveItem("drive", "folder", "scores", "etag", 0, parent_id="root", is_folder=True),
    }
    monkeypatch.setattr(client, "get_item", lambda drive_id, item_id: parents[item_id])

    client.assert_within_root("drive", "file")
    with pytest.raises(ValueError, match="outside the configured OneDrive drive"):
        client.assert_within_root("other", "file")


def test_onedrive_client_resolves_a_safe_relative_folder_to_a_root_checked_id(monkeypatch) -> None:
    monkeypatch.setattr("xw_office.services.product_hub.onedrive.msal.ConfidentialClientApplication", lambda *args, **kwargs: object())
    client = OneDriveAssetClient(tenant_id="tenant", client_id="client", client_secret="secret", root_item_id="drive:root")
    called: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"id": "covers", "name": "Cover-Hintergründe", "eTag": "etag", "size": 0, "folder": {}, "parentReference": {"id": "parent"}}

    def fake_get(url: str, **kwargs: object) -> _Response:
        called["url"] = url
        called["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr(client, "_headers", lambda: {"Authorization": "Bearer test"})
    monkeypatch.setattr(client, "assert_within_root", lambda drive_id, item_id: called.setdefault("checked", (drive_id, item_id)))
    monkeypatch.setattr("xw_office.services.product_hub.onedrive.requests.get", fake_get)

    resolved = client.resolve_relative_folder("02 XeisWorks/29 Web-Grafiken/Cover-Hintergründe")

    assert resolved.item_id == "covers"
    assert called["checked"] == ("drive", "covers")
    assert str(called["url"]).endswith("root:/02%20XeisWorks/29%20Web-Grafiken/Cover-Hintergr%C3%BCnde")
    with pytest.raises(OneDriveConfigurationError, match="relative folder path"):
        client.resolve_relative_folder("02 XeisWorks/../outside")
