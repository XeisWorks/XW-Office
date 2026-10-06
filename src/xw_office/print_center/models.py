"""Print-center contracts and separate SQLAlchemy metadata."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, DateTime, Integer, MetaData, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PrintCenterBase(DeclarativeBase):
    metadata = MetaData(schema="print_center")


class OwnArticle(PrintCenterBase):
    __tablename__ = "article"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    pdf_path: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    print_plan: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PrintStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    range: str = "Alle Seiten"
    profile_id: str = Field(min_length=1)

    @field_validator("range", "profile_id", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ArticleInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=256)
    pdf_path: str = Field(min_length=1)
    notes: str = ""
    print_plan: tuple[PrintStep, ...] = Field(min_length=1)

    @field_validator("name", "pdf_path", "notes", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class PrintArticle(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    source: Literal["official", "own"]
    name: str
    sku: str = ""
    pdf_path: str = ""
    notes: str = ""
    profile_id: str = ""
    print_plan: tuple[PrintStep, ...] = ()
    row_version: int = 1


class PrintReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    copies: int
    job_ids: tuple[str, ...]
