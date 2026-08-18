"""SQLAlchemy models — import for side effects so Alembic sees metadata."""

from xw_office.models.api_secret import ApiSecret
from xw_office.models.base import Base
from xw_office.models.customer_aftercare import CustomerAftercareCase, CustomerAftercareItem
from xw_office.models.expense_check import ExpenseIgnoreRule, ExpenseShiftEntry
from xw_office.models.pc_registry import PcRegistry
from xw_office.models.plc_shipment import PlcShipment
from xw_office.models.settings_kv import SettingKV

__all__ = [
    "ApiSecret",
    "Base",
    "CustomerAftercareCase",
    "CustomerAftercareItem",
    "ExpenseIgnoreRule",
    "ExpenseShiftEntry",
    "PcRegistry",
    "PlcShipment",
    "SettingKV",
]
