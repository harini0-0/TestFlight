"""Pure evaluators. (rule, event, ledger) -> Evaluation. No I/O."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

from glasswing_domain.evaluation import Evaluation, FormulaTrace
from glasswing_domain.money import Money
from glasswing_domain.ontology import Eligibility
from glasswing_domain.rules import RuleIR
from glasswing_domain.transactions import (
    ClockTick,
    Invoice,
    InvoiceLine,
    PerformanceEvent,
    SpendEvent,
)

CENT = Decimal("0.01")
ZERO = Decimal("0")


class LedgerView(Protocol):
    balance: Decimal
    currency: str


def _money(amount: Decimal, currency: str) -> Money:
    return Money(amount=amount.quantize(Decimal("0.0001")), currency=currency)


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(CENT)


def eligible_lines(lines: list[InvoiceLine], eligibility: Eligibility | None) -> list[InvoiceLine]:
    chosen: list[InvoiceLine] = []
    for line in lines:
        category = (line.category or "goods").lower()
        if eligibility is not None:
            excluded = {item.lower() for item in eligibility.exclude}
            included = {item.lower() for item in eligibility.include_categories}
            if category in excluded:
                continue
            if included and category not in included:
                continue
        chosen.append(line)
    return chosen


def line_extended(line: InvoiceLine) -> Decimal:
    return line.extended_amount.amount


def eligible_total(invoice: Invoice, rule: RuleIR) -> Decimal:
    return sum((line_extended(line) for line in eligible_lines(invoice.lines, rule.eligibility)), ZERO)


def actual_rebate(invoice: Invoice, rule: RuleIR) -> Decimal:
    total = ZERO
    for line in eligible_lines(invoice.lines, rule.eligibility):
        if line.rebate_amount is not None:
            total += line.rebate_amount.amount
        elif line.rebate_rate is not None:
            total += line.rebate_rate * line_extended(line)
    return total


def expected_rebate(
    application: str | None,
    rate: Decimal,
    invoice_eligible: Decimal,
    balance_before: Decimal,
    threshold: Decimal,
) -> Decimal | None:
    if application is None:
        return None
    balance_after = balance_before + invoice_eligible
    if balance_after < threshold:
        return ZERO
    if application == "rate_on_each_invoice_once_crossed":
        return _q(rate * invoice_eligible)
    if application == "incremental_above_threshold":
        base = invoice_eligible if balance_before >= threshold else balance_after - threshold
        return _q(rate * base)
    if application == "all_eligible_once_crossed":
        if balance_before >= threshold:
            return ZERO
        return _q(rate * balance_after)
    return None


def _pass(rule: RuleIR, trace: FormulaTrace, explanation: str = "") -> Evaluation:
    return Evaluation(rule_id=rule.rule_id, outcome="pass", formula_trace=trace, explanation=explanation)


def _violation(rule: RuleIR, amount: Decimal, currency: str, trace: FormulaTrace, explanation: str) -> Evaluation:
    return Evaluation(
        rule_id=rule.rule_id,
        outcome="violation",
        amount_at_risk=_money(amount, currency),
        formula_trace=trace,
        explanation=explanation,
    )


def _escalate(rule: RuleIR, trace: FormulaTrace, explanation: str) -> Evaluation:
    return Evaluation(rule_id=rule.rule_id, outcome="escalate", formula_trace=trace, explanation=explanation)


def trigger_matches(rule: RuleIR, event_type: str, supplier_key: str, categories: list[str] | None = None) -> bool:
    if event_type not in rule.trigger:
        return False
    if rule.supplier_key and supplier_key != rule.supplier_key:
        return False
    filters = rule.trigger_filters or {}
    if filters.get("supplier_key") and filters["supplier_key"] != supplier_key:
        return False
    if filters.get("category"):
        wanted = filters["category"].lower()
        have = [item.lower() for item in (categories or [])]
        if wanted not in have:
            return False
    return True


def evaluate_threshold_rebate(rule: RuleIR, invoice: Invoice, balance_before: Decimal) -> tuple[Evaluation, Decimal]:
    eligible = eligible_total(invoice, rule)
    currency = invoice.currency
    if rule.threshold is None or rule.obligation is None:
        trace = FormulaTrace(formula="missing threshold or obligation", result="escalate")
        return _escalate(rule, trace, "rebate rule is incomplete"), eligible
    if "application" in rule.needs_confirmation or rule.obligation.application is None:
        trace = FormulaTrace(
            inputs={"eligible": str(eligible), "balance_before": str(balance_before)},
            formula="application unresolved",
            result="escalate",
        )
        return _escalate(rule, trace, "rebate application mode needs confirmation"), eligible
    expected = expected_rebate(
        rule.obligation.application,
        rule.obligation.rate,
        eligible,
        balance_before,
        rule.threshold.amount,
    )
    actual = actual_rebate(invoice, rule)
    balance_after = balance_before + eligible
    trace = FormulaTrace(
        inputs={
            "eligible": str(eligible),
            "balance_before": str(balance_before),
            "threshold": str(rule.threshold.amount),
            "rate": str(rule.obligation.rate),
            "actual_rebate": str(actual),
            "application": rule.obligation.application,
        },
        formula="expected = rate * invoice eligible once cumulative spend has crossed the threshold",
        intermediates={"balance_after": str(balance_after), "expected_rebate": str(expected)},
        result=str(expected),
    )
    if expected is None:
        return _escalate(rule, trace, "unknown rebate application"), eligible
    leakage = _q(expected - actual)
    if leakage > CENT:
        return (
            _violation(
                rule,
                leakage,
                currency,
                trace,
                f"rebate short by {leakage} {currency}",
            ),
            eligible,
        )
    return _pass(rule, trace, "rebate matches the obligation"), eligible


def evaluate_price_match(rule: RuleIR, invoice: Invoice) -> Evaluation:
    if rule.contracted_price is None:
        return _escalate(rule, FormulaTrace(formula="missing contracted price"), "price rule is incomplete")
    contracted = rule.contracted_price.amount
    leakage = ZERO
    compared = 0
    for line in invoice.lines:
        sku_ok = rule.sku is None or (line.sku or "").lower() == rule.sku.lower()
        desc_ok = rule.description_key is None or rule.description_key.lower() in line.description.lower()
        if rule.sku is None and rule.description_key is None:
            sku_ok = True
        if not (sku_ok and desc_ok):
            continue
        if line.unit_price is None:
            continue
        compared += 1
        delta = line.unit_price.amount - contracted
        if delta > CENT:
            leakage += _q(delta * line.quantity)
    trace = FormulaTrace(
        inputs={"contracted_price": str(contracted), "lines_compared": compared},
        formula="sum((unit_price - contracted_price) * quantity) where unit_price is higher",
        result=str(leakage),
    )
    if compared == 0:
        return _pass(rule, trace, "no matching lines")
    if leakage > CENT:
        return _violation(rule, leakage, invoice.currency, trace, "unit price above contract")
    return _pass(rule, trace, "unit price within contract")


def evaluate_volume_discount(rule: RuleIR, invoice: Invoice) -> Evaluation:
    if rule.contracted_price is None or not rule.tiers:
        return _escalate(rule, FormulaTrace(formula="missing list price or tiers"), "volume rule is incomplete")
    list_price = rule.contracted_price.amount
    leakage = ZERO
    for line in invoice.lines:
        if rule.sku and (line.sku or "").lower() != rule.sku.lower():
            continue
        tier_rate = ZERO
        for tier in sorted(rule.tiers, key=lambda item: item.min_qty):
            if line.quantity >= tier.min_qty:
                tier_rate = tier.discount_rate
        expected_unit = _q(list_price * (Decimal("1") - tier_rate))
        if line.unit_price is None:
            continue
        delta = line.unit_price.amount - expected_unit
        if delta > CENT:
            leakage += _q(delta * line.quantity)
    trace = FormulaTrace(
        formula="expected unit = list * (1 - tier discount); leakage = overcharge * quantity",
        result=str(leakage),
    )
    if leakage > CENT:
        return _violation(rule, leakage, invoice.currency, trace, "volume price not applied")
    return _pass(rule, trace, "volume price matches the tier")


def evaluate_payment_terms(rule: RuleIR, invoice: Invoice) -> Evaluation:
    if rule.discount_percent is None or rule.discount_days is None:
        return _escalate(rule, FormulaTrace(formula="missing payment terms"), "payment rule is incomplete")
    if invoice.paid_date is None:
        return _pass(rule, FormulaTrace(formula="unpaid invoice has no missed discount yet"), "not yet paid")
    elapsed = (invoice.paid_date - invoice.invoice_date).days
    total = invoice.total.amount
    trace = FormulaTrace(
        inputs={"elapsed_days": elapsed, "discount_days": rule.discount_days, "total": str(total)},
        formula="if paid within the window, discount_percent * invoice total must be taken",
    )
    if elapsed > rule.discount_days:
        trace.result = "0"
        return _pass(rule, trace, "paid outside the discount window")
    expected = _q(rule.discount_percent * total)
    actual = invoice.discount_taken.amount if invoice.discount_taken else ZERO
    leakage = _q(expected - actual)
    trace.intermediates = {"expected_discount": str(expected), "actual_discount": str(actual)}
    trace.result = str(leakage)
    if leakage > CENT:
        return _violation(rule, leakage, invoice.currency, trace, "early-payment discount not taken")
    return _pass(rule, trace, "discount taken")


def evaluate_renewal_notice(rule: RuleIR, tick: ClockTick) -> Evaluation:
    if rule.expiry is None or rule.notice_days is None:
        return _escalate(rule, FormulaTrace(formula="missing expiry or notice days"), "renewal rule is incomplete")
    window_start = rule.expiry - timedelta(days=rule.notice_days)
    trace = FormulaTrace(
        inputs={"as_of": tick.as_of.isoformat(), "window_start": window_start.isoformat(), "expiry": rule.expiry.isoformat()},
        formula="notice must be recorded on or before expiry once the notice window has opened",
    )
    if tick.as_of < window_start:
        return _pass(rule, trace, "notice window has not opened")
    if tick.notice_recorded:
        return _pass(rule, trace, "notice recorded")
    return _violation(rule, ZERO, "USD", trace, "renewal notice missing")


def evaluate_sla(rule: RuleIR, event: PerformanceEvent) -> Evaluation:
    if rule.target is None or rule.penalty_rate is None or rule.metric is None:
        return _escalate(rule, FormulaTrace(formula="missing sla fields"), "sla rule is incomplete")
    if event.metric != rule.metric:
        return Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="different metric")
    trace = FormulaTrace(
        inputs={"value": str(event.value), "target": str(rule.target), "penalty_rate": str(rule.penalty_rate)},
        formula="if value < target, penalty = penalty_rate * period spend",
    )
    if event.value >= rule.target:
        return _pass(rule, trace, "sla met")
    base = event.period_spend.amount if event.period_spend else ZERO
    currency = event.period_spend.currency if event.period_spend else "USD"
    leakage = _q(rule.penalty_rate * base)
    trace.result = str(leakage)
    return _violation(rule, leakage, currency, trace, "sla missed")


def spend_eligible(event: SpendEvent, rule: RuleIR) -> Decimal:
    dummy = Invoice(
        transaction_id=event.transaction_id,
        supplier_key=event.supplier_key,
        invoice_number=event.transaction_id,
        invoice_date=event.effective_on,
        currency=event.amount.currency,
        lines=[
            InvoiceLine(
                category=event.category,
                extended_amount=event.amount,
            )
        ],
    )
    return eligible_total(dummy, rule)


def event_date(event: object) -> date:
    if isinstance(event, Invoice):
        return event.invoice_date
    if isinstance(event, SpendEvent):
        return event.effective_on
    if isinstance(event, PerformanceEvent):
        return event.reported_on
    if isinstance(event, ClockTick):
        return event.as_of
    from glasswing_domain.transactions import PurchaseOrder

    if isinstance(event, PurchaseOrder):
        return event.ordered_on
    raise TypeError(type(event))
