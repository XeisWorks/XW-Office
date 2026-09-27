from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xw_office.models.base import Base
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.services.product_hub.onedrive import OneDriveItem
from xw_office.services.product_hub.onedrive_assets import OneDriveAssetService


class _Client:
    root_drive_id = "drive"

    def get_item(self, drive_id: str, item_id: str) -> OneDriveItem:
        return OneDriveItem(drive_id, item_id, "score.pdf", "etag", 123)

    def assert_within_root(self, drive_id: str, item_id: str) -> None:
        if drive_id != self.root_drive_id:
            raise ValueError("outside root")

    def list_children(self, item_id: str | None = None) -> list[OneDriveItem]:
        return [OneDriveItem("drive", "child", "score.pdf", "etag", 123)]


def test_attach_stores_private_stable_onedrive_reference(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'hub.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    product, _ = ProductHubRepository(factory).create_product(sku="XW-OD", name="Score")
    asset = OneDriveAssetService(factory, _Client()).attach(product_id=product.id, role="PRINT_PDF", drive_id="drive", item_id="item")
    assert asset.storage_kind == "ONEDRIVE"
    assert asset.uri == "onedrive://drive/item"
    assert asset.source_external_id == "drive:item"
    assert asset.source_version == "etag"
    assert asset.public_share_allowed is False


def test_asset_service_refuses_a_drive_outside_the_configured_root(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'hub.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    product, _ = ProductHubRepository(factory).create_product(sku="XW-OD-2", name="Score")

    import pytest
    with pytest.raises(ValueError, match="outside root"):
        OneDriveAssetService(factory, _Client()).attach(
            product_id=product.id, role="PRINT_PDF", drive_id="other", item_id="item"
        )


def test_list_children_delegates_to_the_private_graph_client(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'hub.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    items = OneDriveAssetService(factory, _Client()).list_children()
    assert [(item.item_id, item.name) for item in items] == [("child", "score.pdf")]
