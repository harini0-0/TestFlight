"""Ledger math and the live evaluation path. Sandbox writes never touch this ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from glasswing_domain.evaluation import Evaluation
from glasswing_domain.rules import RuleIR
from glasswing_domain.transactions import ClockTick, Invoice, PerformanceEvent, SpendEvent

from control_engine.evaluators import (
    ZERO,
    evaluate_payment_terms,
    evaluate_price_match,
    evaluate_renewal_notice,
    evaluate_sla,
    evaluate_threshold_rebate,
    evaluate_volume_discount,
    event_date,
    spend_eligible,
    trigger_matches,
)


@dataclass
class LedgerAccount:
    tenant_id: str
    supplier_key: str
    contract_id: str
    rule_id: str
    period_key: str
    metric: str
    balance: Decimal = ZERO
    currency: str = "USD"
    applied_ids: set[str] = field(default_factory=set)
    version: int = 0

    def apply(self, transaction_id: str, amount: Decimal) -> Decimal:
        if transaction_id in self.applied_ids:
            return self.balance
        self.balance += amount
        self.applied_ids.add(transaction_id)
        self.version += 1
        return self.balance


@dataclass
class LiveResult:
    evaluation: Evaluation
    ledger_delta: Decimal = ZERO
    period_key: str = ""


def evaluate_condition(
    rule: RuleIR,
    event: Invoice | SpendEvent | PerformanceEvent | ClockTick,
    balance_before: Decimal,
) -> tuple[Evaluation, Decimal]:
    """Return the evaluation and the eligible amount that should move the ledger."""
    event_type = event.event_type
    supplier = event.supplier_key
    categories: list[str] = []
    if isinstance(event, Invoice):
        categories = [line.category for line in event.lines]
    elif isinstance(event, SpendEvent):
        categories = [event.category]
    if not trigger_matches(rule, event_type, supplier, categories):
        return Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="trigger did not match"), ZERO
    if rule.kind != "condition":
        return Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="not a condition rule"), ZERO
    if rule.rule_type == "threshold_rebate" and isinstance(event, Invoice):
        evaluation, eligible = evaluate_threshold_rebate(rule, event, balance_before)
        return evaluation, eligible
    if rule.rule_type == "threshold_rebate" and isinstance(event, SpendEvent):
        eligible = spend_eligible(event, rule)
        from glasswing_domain.evaluation import FormulaTrace

        trace = FormulaTrace(
            inputs={"eligible": str(eligible), "balance_before": str(balance_before)},
            formula="spend adjustment increases eligible balance only",
            result=str(balance_before + eligible),
        )
        return Evaluation(rule_id=rule.rule_id, outcome="pass", formula_trace=trace), eligible
    if rule.rule_type == "price_match" and isinstance(event, Invoice):
        return evaluate_price_match(rule, event), ZERO
    if rule.rule_type == "volume_discount" and isinstance(event, Invoice):
        return evaluate_volume_discount(rule, event), ZERO
    if rule.rule_type == "payment_terms" and isinstance(event, Invoice):
        return evaluate_payment_terms(rule, event), ZERO
    if rule.rule_type == "renewal_notice" and isinstance(event, ClockTick):
        return evaluate_renewal_notice(rule, event), ZERO
    if rule.rule_type == "sla_penalty" and isinstance(event, PerformanceEvent):
        return evaluate_sla(rule, event), ZERO
    return Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="event does not apply"), ZERO


def natural_language_applicable(rule: RuleIR, event: Invoice | SpendEvent | PerformanceEvent | ClockTick) -> bool:
    if rule.kind != "natural_language" and rule.rule_type != "natural_language":
        return False
    categories: list[str] = []
    if isinstance(event, Invoice):
        categories = [line.category for line in event.lines]
    elif isinstance(event, SpendEvent):
        categories = [event.category]
    return trigger_matches(rule, event.event_type, event.supplier_key, categories)


def as_of(event: Invoice | SpendEvent | PerformanceEvent | ClockTick):
    return event_date(event)
