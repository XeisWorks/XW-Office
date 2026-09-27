"""Server-side, app-only Microsoft Graph access for private product assets."""
from __future__ import annotations

import os
from dataclasses import dataclass

import msal
import requests


class OneDriveConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OneDriveItem:
    drive_id: str
    item_id: str
    name: str
    etag: str
    size: int


class OneDriveAssetClient:
    """Uses client credentials; never exposes Graph tokens to browser clients."""

    def __init__(self, *, tenant_id: str, client_id: str, client_secret: str, root_item_id: str = "") -> None:
        self.tenant_id, self.client_id, self.client_secret = tenant_id.strip(), client_id.strip(), client_secret.strip()
        self.root_item_id = root_item_id.strip()
        if not all((self.tenant_id, self.client_id, self.client_secret, self.root_item_id)):
            raise OneDriveConfigurationError("OneDrive server access is not configured")
        if "\\" in self.root_item_id or ":" not in self.root_item_id:
            raise OneDriveConfigurationError("XW_ONEDRIVE_ROOT must be drive_id:item_id")
        self.root_drive_id, self.root_item_id = self.root_item_id.split(":", 1)
        if not self.root_drive_id or not self.root_item_id:
            raise OneDriveConfigurationError("XW_ONEDRIVE_ROOT must be drive_id:item_id")
        self._app = msal.ConfidentialClientApplication(self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant_id}", client_credential=self.client_secret)

    @classmethod
    def from_environment(cls) -> "OneDriveAssetClient":
        return cls(tenant_id=os.getenv("MS_GRAPH_TENANT_ID", ""), client_id=os.getenv("MS_GRAPH_CLIENT_ID", ""), client_secret=os.getenv("MS_GRAPH_CLIENT_SECRET", ""), root_item_id=os.getenv("XW_ONEDRIVE_ROOT", ""))

    def _headers(self) -> dict[str, str]:
        result = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        token = str(result.get("access_token") or "")
        if not token:
            raise OneDriveConfigurationError("Microsoft Graph token acquisition failed")
        return {"Authorization": f"Bearer {token}"}

    def get_item(self, drive_id: str, item_id: str) -> OneDriveItem:
        response = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}", headers=self._headers(), timeout=30)
        response.raise_for_status()
        payload = response.json()
        return OneDriveItem(drive_id=drive_id, item_id=item_id, name=str(payload.get("name") or ""), etag=str(payload.get("eTag") or ""), size=int(payload.get("size") or 0))

    def get_root(self) -> OneDriveItem:
        return self.get_item(self.root_drive_id, self.root_item_id)

    def download(self, drive_id: str, item_id: str) -> bytes:
        response = requests.get(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content", headers=self._headers(), timeout=60)
        response.raise_for_status()
        return response.content
