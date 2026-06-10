"""Product pipeline public API."""
from xw_studio.services.products.catalog import (
    Product,
    ProductCatalogService,
    PrintRule,
    StockStatus,
)
from xw_studio.services.products.pdf_bulk_mapper import (
    BulkScanResult,
    PdfBulkMapper,
    PdfCandidate,
    ProductMatch,
    ReviewItem,
)
from xw_studio.services.products.brand_service import (
    BrandBulkUpdateReport,
    BrandUpdateItem,
    ProductBrandService,
)

__all__ = [
    "Product",
    "ProductCatalogService",
    "PrintRule",
    "StockStatus",
    "BulkScanResult",
    "PdfBulkMapper",
    "PdfCandidate",
    "ProductMatch",
    "ReviewItem",
    "BrandBulkUpdateReport",
    "BrandUpdateItem",
    "ProductBrandService",
]
