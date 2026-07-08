"""EU-OSS quarter calculation models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class OssLine(BaseModel):
    """One aggregated EU-OSS line for a country/rate/type combination."""

    country_code: str
    country_name: str
    vat_rate: str
    taxable_amount: str
    tax_amount: str
    goods: bool = True
    source_docs: list[str] = Field(default_factory=list)


class OssQuarterResult(BaseModel):
    """Calculated EU-OSS quarter result."""

    year: int
    quarter: int
    goods_lines: list[OssLine] = Field(default_factory=list)
    service_lines: list[OssLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_count: int = 0
    excluded_count: int = 0


class OssXmlExport(BaseModel):
    """XML export payload for manual portal upload."""

    year: int
    quarter: int
    file_name: str
    xml_payload: str
    line_count: int
    warnings: list[str] = Field(default_factory=list)