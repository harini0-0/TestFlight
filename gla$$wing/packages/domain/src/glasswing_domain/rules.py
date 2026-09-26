"""Versioned procurement rule intermediate representation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from glasswing_domain.money import Money
from glasswing_domain.ontology import DiscountTier, Eligibility, Period

IR_VERSION = "1.0"
ApplicationMode = Literal[
    "incremental_above_threshold",
    "all_eligible_once_crossed",
    "rate_on_each_invoice_once_crossed",
]
RuleKind = Literal["condition", "natural_language"]
RuleType = Literal[
    "price_match",
    "threshold_rebate",
    "volume_discount",
    "payment_terms",
    "renewal_notice",
    "sla_penalty",
    "natural_language",
]

# The engine only scores these event names. Model output often uses nearby words.
_ENGINE_TRIGGERS: dict[str, list[str]] = {
    "price_match": ["invoice.posted"],
    "threshold_rebate": ["invoice.posted", "spend.adjusted"],
    "volume_discount": ["invoice.posted"],
    "payment_terms": ["invoice.posted"],
    "renewal_notice": ["clock.tick"],
    "sla_penalty": ["performance.reported"],
}
_TRIGGER_ALIASES = {
    "invoice.posted": "invoice.posted",
    "invoice_posted": "invoice.posted",
    "invoice_line": "invoice.posted",
    "invoice": "invoice.posted",
    "spend.adjusted": "spend.adjusted",
    "spend_adjusted": "spend.adjusted",
    "performance.reported": "performance.reported",
    "period_close": "performance.reported",
    "quarter_close": "performance.reported",
    "clock.tick": "clock.tick",
    "notice_window": "clock.tick",
}


def engine_triggers(rule_type: str, trigger: list[str]) -> list[str]:
    """Map a rule onto the event names the engine actually scores."""
    fixed = _ENGINE_TRIGGERS.get(rule_type)
    if fixed is not None:
        return list(fixed)
    mapped: list[str] = []
    for item in trigger:
        canonical = _TRIGGER_ALIASES.get(item.strip().lower().replace(" ", "_"))
        if canonical and canonical not in mapped:
            mapped.append(canonical)
    return mapped or ["invoice.posted"]
ValueBand = Literal["low", "high", "unknown"]
RiskBand = Literal["low", "high"]


class Threshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["eligible_spend", "eligible_volume"] = "eligible_spend"
    op: Literal["gte"] = "gte"
    amount: Decimal
    currency: str = "USD"

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("threshold amounts must not be floats")
        return Decimal(str(value))


class Obligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: Decimal
    application: ApplicationMode | None = None

    @field_validator("rate", mode="before")
    @classmethod
    def _rate(cls, value: Any) -> Decimal:
        if isinstance(value, float):
            raise TypeError("rates must not be floats")
        return Decimal(str(value))


class RuleIR(BaseModel):
    """Executable rule. Unknown ir_version is rejected by the engine."""

    model_config = ConfigDict(extra="forbid")

    ir_version: Literal["1.0"] = "1.0"
    rule_id: str
    kind: RuleKind
    rule_type: RuleType
    supplier_key: str
    source_clause_ids: list[str] = Field(min_length=1)
    trigger: list[str] = Field(min_length=1)
    assertion: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    needs_confirmation: list[str] = []
    period: Period | None = None
    eligibility: Eligibility | None = None
    threshold: Threshold | None = None
    obligation: Obligation | None = None
    sku: str | None = None
    description_key: str | None = None
    contracted_price: Money | None = None
    tiers: list[DiscountTier] = []
    discount_percent: Decimal | None = None
    discount_days: int | None = None
    net_days: int | None = None
    notice_days: int | None = None
    expiry: date | None = None
    metric: str | None = None
    target: Decimal | None = None
    penalty_rate: Decimal | None = None
    clause_text: str | None = None
    decision_prompt: str | None = None
    trigger_filters: dict[str, str] = {}
    value_band: ValueBand = "unknown"
    risk_band: RiskBand = "low"
    warning_reasons: list[str] = []
    value_amount: Money | None = None
    human_required: bool = False

    @field_validator("discount_percent", "target", "penalty_rate", mode="before")
    @classmethod
    def _optional_decimal(cls, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            raise TypeError("decimals must not be floats")
        return Decimal(str(value))

    def warned(self) -> bool:
        return self.value_band == "high" or self.risk_band == "high"


class PolicyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    document_id: str
    tenant_id: str
    supplier_key: str
    version: int
    effective_date: date
    expiry: date | None = None
    document_hash: str
    prompt_hash: str
    model_id: str
    rules: list[RuleIR]
    test_run_id: str | None = None
    status: Literal["draft", "approved", "superseded"] = "draft"
