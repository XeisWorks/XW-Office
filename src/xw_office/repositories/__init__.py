"""Data access helpers — one module per aggregate; accept SQLAlchemy :class:`~sqlalchemy.orm.Session`."""

from xw_office.repositories.api_secret import ApiSecretRepository
from xw_office.repositories.customer_aftercare import CustomerAftercareRepository
from xw_office.repositories.digital_license_fulfillment import DigitalLicenseFulfillmentRepository
from xw_office.repositories.expense_check import ExpenseCheckRepository
from xw_office.repositories.pc_registry import PcRegistryRepository
from xw_office.repositories.plc_shipment import PlcShipmentRepository
from xw_office.repositories.product_hub import ProductHubRepository
from xw_office.repositories.settings_kv import SettingKvRepository

__all__ = [
    "ApiSecretRepository",
    "CustomerAftercareRepository",
    "DigitalLicenseFulfillmentRepository",
    "ExpenseCheckRepository",
    "PcRegistryRepository",
    "PlcShipmentRepository",
    "ProductHubRepository",
    "SettingKvRepository",
]
