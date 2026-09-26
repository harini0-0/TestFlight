"""Canonical business events. ERP field names never appear here."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from glasswing_domain.money import Money


class InvoiceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = None
    description: str = ""
    category: str = "goods"
    quantity: Decimal = Decimal("1")
    unit_price: Money | None = None
    extended_amount: Money
    rebate_rate: Decimal | None = None
    rebate_amount: Money | None = None

    @field_validator("quantity", "rebate_rate", mode="before")
    @classmethod
    def _decimal(cls, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            raise TypeError("decimals must not be floats")
        return Decimal(str(value))


class Invoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["invoice.posted"] = "invoice.posted"
    transaction_id: str
    supplier_key: str
    invoice_number: str
    currency: str = "USD"
    invoice_date: date
    paid_date: date | None = None
    discount_taken: Money | None = None
    lines: list[InvoiceLine] = Field(min_length=1)

    @property
    def total(self) -> Money:
        amount = sum((line.extended_amount.amount for line in self.lines), Decimal("0"))
        return Money(amount=amount, currency=self.currency)


class PurchaseOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["purchase_order.opened"] = "purchase_order.opened"
    transaction_id: str
    supplier_key: str
    po_number: str
    currency: str = "USD"
    ordered_on: date
    lines: list[InvoiceLine] = Field(min_length=1)


class SpendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["spend.adjusted"] = "spend.adjusted"
    transaction_id: str
    supplier_key: str
    category: str = "goods"
    amount: Money
    effective_on: date
    reason: str = ""


class PerformanceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["performance.reported"] = "performance.reported"
    transaction_id: str
    supplier_key: str
    metric: str
    value: Decimal
    period_spend: Money | None = None
    narrative: str = ""
    reported_on: date

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("performance values must not be floats")
        return Decimal(str(value))


class ClockTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["clock.tick"] = "clock.tick"
    transaction_id: str
    supplier_key: str
    as_of: date
    notice_recorded: bool = False


CanonicalEvent = Invoice | PurchaseOrder | SpendEvent | PerformanceEvent | ClockTick
