"""SQLAlchemy models — import for side effects so Alembic sees metadata."""

from xw_office.models.api_secret import ApiSecret
from xw_office.models.base import Base
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.models.digital_license_fulfillment import DigitalLicenseFulfillment
from xw_office.models.expense_check import ExpenseIgnoreRule, ExpenseShiftEntry
from xw_office.models.pc_registry import PcRegistry
from xw_office.models.plc_shipment import PlcShipment
from xw_office.models.product_hub import (
    AuditLog,
    Category,
    ChannelCategoryMapping,
    ChannelMapping,
    PriceList,
    PrintRule,
    Product,
    ProductAsset,
    ProductCategory,
    ProductEdition,
    ProductFamily,
    ProductIdentifier,
    ProductImprovement,
    ProductPrice,
    ProductSkuAlias,
    ProductTag,
    ProductVariant,
    Tag,
)
from xw_office.models.product_hub_import import (
    ImportBatch,
    ImportMatchCandidate,
    StagingAsset,
    StagingCategory,
    StagingIdentifier,
    StagingInventory,
    StagingProduct,
    StagingVariant,
)
from xw_office.models.product_hub_inventory import (
    InventoryAlert,
    InventoryLocation,
    InventoryMovement,
    InventoryStock,
)
from xw_office.models.product_hub_sharing import ExportLog, SharedCatalogView
from xw_office.models.product_hub_sync import (
    ExternalPayloadArchive,
    OutboxEvent,
    SyncConflict,
    SyncCursor,
    SyncItem,
    SyncJob,
)
from xw_office.models.settings_kv import SettingKV

__all__ = [
    "ApiSecret",
    "AuditLog",
    "Base",
    "Category",
    "ChannelCategoryMapping",
    "ChannelMapping",
    "CustomerAftercareCase",
    "CustomerAftercareItem",
    "DigitalLicenseFulfillment",
    "ExpenseIgnoreRule",
    "ExpenseShiftEntry",
    "ExportLog",
    "ExternalPayloadArchive",
    "ImportBatch",
    "ImportMatchCandidate",
    "InventoryAlert",
    "InventoryLocation",
    "InventoryMovement",
    "InventoryStock",
    "OutboxEvent",
    "PcRegistry",
    "PlcShipment",
    "PriceList",
    "PrintRule",
    "Product",
    "ProductAsset",
    "ProductCategory",
    "ProductEdition",
    "ProductFamily",
    "ProductIdentifier",
    "ProductImprovement",
    "ProductPrice",
    "ProductSkuAlias",
    "ProductTag",
    "ProductVariant",
    "SettingKV",
    "SharedCatalogView",
    "StagingAsset",
    "StagingCategory",
    "StagingIdentifier",
    "StagingInventory",
    "StagingProduct",
    "StagingVariant",
    "SyncConflict",
    "SyncCursor",
    "SyncItem",
    "SyncJob",
    "Tag",
]
