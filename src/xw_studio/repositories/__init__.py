"""Data access helpers — one module per aggregate; accept SQLAlchemy :class:`~sqlalchemy.orm.Session`."""

from xw_studio.repositories.api_secret import ApiSecretRepository
from xw_studio.repositories.pc_registry import PcRegistryRepository
from xw_studio.repositories.plc_shipment import PlcShipmentRepository
from xw_studio.repositories.settings_kv import SettingKvRepository

__all__ = ["ApiSecretRepository", "PcRegistryRepository", "PlcShipmentRepository", "SettingKvRepository"]
