"""Shared type definitions and enums."""
from enum import Enum, auto


class ModuleKey(str, Enum):
    """Sidebar module identifiers."""
    HOME = "home"
    RECHNUNGEN = "rechnungen"
    GUTSCHEINE = "gutscheine"
    MOLLIE = "mollie"
    PRODUCTS = "products"
    CRM = "crm"
    TAXES = "taxes"
    CLEARING = "clearing"
    STATISTICS = "statistics"
    LAYOUT = "layout"
    CALCULATION = "calculation"
    TRAVEL_COSTS = "travel_costs"
    MARKETING = "marketing"
    NOTATION = "notation"
    XW_COPILOT = "xw_copilot"
    WUEDARAMUSI = "wuedaramusi"
    SETTINGS = "settings"


class PrinterStatus(Enum):
    """Traffic light printer status."""
    GREEN = auto()
    YELLOW = auto()
    RED = auto()


class BadgeSeverity(str, Enum):
    """Badge notification severity."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
