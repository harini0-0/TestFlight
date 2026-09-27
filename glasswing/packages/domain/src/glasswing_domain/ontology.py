"""Commercial ontology extracted from a supplier contract."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from glasswing_domain.money import Money


class Supplier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_key: str
    name: str


class Period(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["contract_year", "calendar_year"] = "contract_year"
    anchor: Literal["effective_date", "calendar"] = "effective_date"


class Eligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_categories: list[str] = []
    exclude: list[str] = []


class Clause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_id: str
    section: str
    heading: str = ""
    text: str
    page: int = 1
    bbox: list[float] = []
    commercial: bool = True


class PriceTerm(BaseModel):
    sku: str
    unit_price: Money
    clause_id: str


class RebateTerm(BaseModel):
    rate: Decimal
    threshold: Money
    clause_id: str

    @field_validator("rate", mode="before")
    @classmethod
    def _rate(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("rates must not be floats")
        return Decimal(str(value))


class DiscountTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_qty: Decimal
    discount_rate: Decimal

    @field_validator("min_qty", "discount_rate", mode="before")
    @classmethod
    def _dec(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("decimals must not be floats")
        return Decimal(str(value))


class PaymentTerm(BaseModel):
    discount_percent: Decimal
    discount_days: int
    net_days: int
    clause_id: str


class SlaTerm(BaseModel):
    metric: str
    target: Decimal
    penalty_rate: Decimal
    clause_id: str


class PenaltyTerm(BaseModel):
    description: str
    clause_id: str


class ContractDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    supplier: Supplier
    effective_date: date
    expiry: date | None = None
    clauses: list[Clause] = []
