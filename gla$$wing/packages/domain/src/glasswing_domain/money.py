"""Currency amounts. Floats are rejected."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class Money(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str = "USD"

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("money amounts must be Decimal or str, not float")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid money amount: {value}") from exc
        return parsed.quantize(Decimal("0.0001"))

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        code = value.upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency must be an ISO 4217 alpha code")
        return code

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError("currency mismatch")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError("currency mismatch")
        return Money(amount=self.amount - other.amount, currency=self.currency)
