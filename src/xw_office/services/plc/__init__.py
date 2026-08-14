"""PLC integration helpers for post label center exports."""

from xw_office.services.plc.customs_document import (
    PlcCustomsDocumentError,
    build_customs_a5_print_pdf,
    customs_a5_print_path,
    ensure_customs_a5_print_file,
)
from xw_office.services.plc.polling import (
    DEFAULT_PLC_IMPORT_DIR,
    DEFAULT_TEST_PLC_IMPORT_DIR,
    PlcConfig,
    ShipmentAddress,
    build_postdefaultport_lines,
    normalize_shipment_address,
    write_import_file,
)
from xw_office.services.plc.models import (
    PlcCustomsArticle,
    PlcParcel,
    PlcShipmentDraft,
    build_polling_lines,
    clean_reference,
    parse_shipment_address_lines,
)
from xw_office.services.plc.service import PlcShipmentService
from xw_office.services.plc.label_archive import PlcLabelArchive
from xw_office.services.plc.webservice import (
    PlcWebserviceClient,
    PlcWebserviceResult,
    PlcWebserviceSettings,
    webservice_settings_from_secrets,
)

__all__ = [
    "DEFAULT_PLC_IMPORT_DIR",
    "DEFAULT_TEST_PLC_IMPORT_DIR",
    "PlcCustomsDocumentError",
    "PlcConfig",
    "ShipmentAddress",
    "build_postdefaultport_lines",
    "normalize_shipment_address",
    "write_import_file",
    "PlcCustomsArticle",
    "PlcParcel",
    "PlcShipmentDraft",
    "build_polling_lines",
    "build_customs_a5_print_pdf",
    "clean_reference",
    "customs_a5_print_path",
    "ensure_customs_a5_print_file",
    "parse_shipment_address_lines",
    "PlcShipmentService",
    "PlcLabelArchive",
    "PlcWebserviceClient",
    "PlcWebserviceResult",
    "PlcWebserviceSettings",
    "webservice_settings_from_secrets",
]
