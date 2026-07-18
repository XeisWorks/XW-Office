"""Typed Phase-2 UVA calculation models."""
from __future__ import annotations

from pydantic import BaseModel, Field


class UvaKennzahlen(BaseModel):
    """Subset of Austrian U30 fields used in the phase-2 integration."""

    A000: str = "0.00"
    A011: str = "0.00"
    A017: str = "0.00"
    A021: str = "0.00"
    A022: str = "0.00"
    A029: str = "0.00"
    A006: str = "0.00"
    A057: str = "0.00"
    B070: str = "0.00"
    B072: str = "0.00"
    C060: str = "0.00"
    C065: str = "0.00"
    C066: str = "0.00"
    D090: str = "0.00"


class UvaPayloadResult(BaseModel):
    """Calculated phase-2 UVA payload with audit information."""

    year: int
    month: int
    kennzahlen: UvaKennzahlen
    zahlbetrag: str = "0.00"
    rule_version: str = "U30_01_2022"
    warnings: list[str] = Field(default_factory=list)
