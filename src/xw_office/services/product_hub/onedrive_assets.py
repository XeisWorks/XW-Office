"""Attach private OneDrive references to Hub assets without downloading PDFs."""
from __future__ import annotations

import uuid
from sqlalchemy.orm import sessionmaker

from xw_office.core.database import session_scope
from xw_office.models.product_hub import ProductAsset
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.onedrive import OneDriveAssetClient


class OneDriveAssetService:
    def __init__(self, session_factory: sessionmaker, client: OneDriveAssetClient) -> None:
        self._session_factory, self._client = session_factory, client

    def attach(self, *, product_id: uuid.UUID, role: str, drive_id: str, item_id: str,
               variant_id: uuid.UUID | None = None) -> ProductAsset:
        self._client.assert_within_root(drive_id, item_id)
        item = self._client.get_item(drive_id, item_id)
        if item.is_folder:
            raise ValueError("A OneDrive folder cannot be attached as a product asset")
        with session_scope(self._session_factory) as session:
            repo = ProductHubRepository(session)
            if repo.get_product(product_id) is None:
                raise KeyError(f"Product {product_id} not found")
            return repo.add_asset(product_id=product_id, variant_id=variant_id, role=role,
                storage_kind="ONEDRIVE", uri=f"onedrive://{item.drive_id}/{item.item_id}",
                source_channel="onedrive", source_external_id=f"{item.drive_id}:{item.item_id}",
                source_version=item.etag,
                original_filename=item.name, size_bytes=item.size, public_share_allowed=False)

    def list_children(self, item_id: str | None = None):
        return self._client.list_children(item_id)
