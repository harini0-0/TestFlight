"""Template cases plus the contract test agent."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from glasswing_domain.evaluation import TestCase
from glasswing_domain.ids import uuid7
from glasswing_domain.rules import RuleIR

from compiler.pipeline import compile_clause_deterministic  # noqa: F401  (re-export convenience)


def _case(rule: RuleIR, title: str, events: list[dict], outcome: str, amount: str | None, **kwargs) -> TestCase:
    return TestCase(
        case_id=f"case-{uuid7()}",
        rule_id=rule.rule_id,
        author="template",
        title=title,
        events=events,
        expected_outcome=outcome,  # type: ignore[arg-type]
        expected_amount=Decimal(amount) if amount is not None else None,
        **kwargs,
    )


def _invoice(rule: RuleIR, number: str, amount: str, category: str = "goods", rebate: str | None = None, day: int = 1, sku: str | None = None, unit: str | None = None, qty: str = "1") -> dict:
    extended = Decimal(amount)
    quantity = Decimal(qty)
    unit_price = Decimal(unit) if unit else (extended / quantity if quantity else extended)
    line = {
        "sku": sku or rule.sku,
        "description": sku or rule.sku or "goods",
        "category": category,
        "quantity": str(quantity),
        "unit_price": {"amount": str(unit_price), "currency": "USD"},
        "extended_amount": {"amount": str(extended), "currency": "USD"},
    }
    if rebate is not None:
        line["rebate_amount"] = {"amount": rebate, "currency": "USD"}
    return {
        "event_type": "invoice.posted",
        "transaction_id": f"tx-{number}",
        "supplier_key": rule.supplier_key,
        "invoice_number": number,
        "currency": "USD",
        "invoice_date": f"2026-01-{day:02d}",
        "lines": [line],
    }


def template_cases(rule: RuleIR) -> list[TestCase]:
    if rule.rule_type == "threshold_rebate" and rule.threshold and rule.obligation and rule.obligation.application:
        threshold = rule.threshold.amount
        rate = rule.obligation.rate
        below = _q(threshold / Decimal("2"))
        later = Decimal("84000")
        application = rule.obligation.application
        if application == "incremental_above_threshold":
            cross_amount = _q(rate * Decimal("50"))
            later_amount = _q(rate * later)
            exact_amount = _q(rate * Decimal("0"))  # exactly on the line, excess is 0 for incremental? 
            # balance_before 0, invoice == threshold, base = threshold - 0? 
            # balance_before >= threshold is false, base = balance_after - threshold = 0.
            exact_outcome = "pass"
            exact_amount = Decimal("0")
        elif application == "all_eligible_once_crossed":
            cross_amount = _q(rate * (threshold + Decimal("50")))
            later_amount = Decimal("0")
            exact_outcome = "violation"
            exact_amount = _q(rate * threshold)
        else:
            cross_amount = _q(rate * Decimal("150"))
            later_amount = _q(rate * later)
            exact_outcome = "violation"
            exact_amount = _q(rate * threshold)
        exact_rebate = _q(rate * threshold)
        later_outcome = "violation" if later_amount > Decimal("0") else "pass"
        return [
            _case(rule, "spend below the threshold", [_invoice(rule, "BELOW", str(below), rebate="0")], "pass", "0"),
            _case(
                rule,
                "spend exactly on the threshold with no rebate",
                [_invoice(rule, "EXACT", str(threshold), rebate="0")],
                exact_outcome,
                str(exact_amount),
            ),
            _case(
                rule,
                "invoice that crosses the threshold",
                [
                    _invoice(rule, "PRE", str(threshold - Decimal("100")), rebate="0", day=2),
                    _invoice(rule, "CROSS", "150", rebate="0", day=3),
                ],
                "violation",
                str(cross_amount),
            ),
            _case(
                rule,
                "later invoice missing the rebate",
                [
                    _invoice(rule, "BASE", str(threshold), rebate=str(exact_rebate), day=4),
                    _invoice(rule, "LATER", str(later), rebate="0", day=5),
                ],
                later_outcome,
                str(later_amount),
            ),
            _case(
                rule,
                "later invoice with the correct rebate",
                [
                    _invoice(rule, "BASE2", str(threshold), rebate=str(exact_rebate), day=6),
                    _invoice(rule, "OK", str(later), rebate=str(later_amount if later_amount > 0 else exact_rebate), day=7),
                ],
                "pass",
                "0",
            ),
            _case(
                rule,
                "freight is excluded from eligible spend",
                [_invoice(rule, "FR", "5000000", category="freight", rebate="0", day=8)],
                "pass",
                "0",
            ),
        ]
    if rule.rule_type == "price_match" and rule.contracted_price is not None:
        price = rule.contracted_price.amount
        over = price + Decimal("2")
        under = price - Decimal("1")
        return [
            _case(rule, "unit price matches", [_invoice(rule, "P1", str(price), unit=str(price), qty="2")], "pass", "0"),
            _case(
                rule,
                "unit price overcharge",
                [_invoice(rule, "P2", str(over * 3), unit=str(over), qty="3")],
                "violation",
                str(_q((over - price) * 3)),
            ),
            _case(rule, "unit price under contract", [_invoice(rule, "P3", str(under), unit=str(under))], "pass", "0"),
        ]
    if rule.rule_type == "payment_terms" and rule.discount_percent and rule.discount_days:
        return [
            _case(rule, "unpaid invoice", [_invoice(rule, "PAY1", "1000")], "pass", "0"),
        ]
    if rule.rule_type == "renewal_notice" and rule.expiry and rule.notice_days:
        inside = rule.expiry - timedelta(days=1)
        past = rule.expiry + timedelta(days=1)
        before = rule.expiry - timedelta(days=rule.notice_days + 5)
        return [
            _case(rule, "inside the notice window", [_tick(rule, inside, False)], "violation", "0"),
            _case(rule, "past the notice deadline", [_tick(rule, past, False)], "violation", "0"),
            _case(rule, "before the notice window", [_tick(rule, before, False)], "pass", None),
        ]
    if rule.rule_type == "sla_penalty" and rule.target is not None:
        return [
            _case(rule, "sla met", [_perf(rule, str(rule.target))], "pass", "0"),
            _case(
                rule,
                "sla missed",
                [_perf(rule, str(rule.target - Decimal("0.05")), spend="1000")],
                "violation",
                str(_q((rule.penalty_rate or Decimal("0")) * Decimal("1000"))),
            ),
        ]
    if rule.rule_type == "volume_discount" and rule.tiers and rule.contracted_price:
        tier = max(rule.tiers, key=lambda item: item.min_qty)
        expected_unit = _q(rule.contracted_price.amount * (Decimal("1") - tier.discount_rate))
        qty = tier.min_qty
        extended = expected_unit * qty
        over_unit = expected_unit + Decimal("1")
        return [
            _case(
                rule,
                "tier price honored",
                [_invoice(rule, "V1", str(extended), unit=str(expected_unit), qty=str(qty))],
                "pass",
                "0",
            ),
            _case(
                rule,
                "tier price missed",
                [_invoice(rule, "V2", str(over_unit * qty), unit=str(over_unit), qty=str(qty))],
                "violation",
                str(_q(Decimal("1") * qty)),
            ),
        ]
    if rule.rule_type == "natural_language":
        clause_id = rule.source_clause_ids[0]
        triggers = set(rule.trigger or [])
        if "invoice.posted" in triggers:
            breach = _invoice(rule, "NL1", "10")
            breach["lines"][0]["description"] = "The supplier did not prioritize the buyer during the shortage."
            matched = [breach]
        else:
            matched = [_perf(rule, "0", narrative="The supplier did not prioritize the buyer during the shortage.")]
        return [
            _case(
                rule,
                "trigger miss skips the model",
                [_tick(rule, date(2026, 1, 2), False)],
                "skipped",
                None,
                expect_model_call=False,
            ),
            _case(
                rule,
                "trigger match returns a judgment",
                matched,
                "violation",
                None,
                expect_model_call=True,
                cite_clause_id=clause_id,
            ),
        ]
    return []


def _tick(rule: RuleIR, day: date, notice: bool) -> dict:
    return {
        "event_type": "clock.tick",
        "transaction_id": f"tick-{day.isoformat()}",
        "supplier_key": rule.supplier_key,
        "as_of": day.isoformat(),
        "notice_recorded": notice,
    }


def _perf(rule: RuleIR, value: str, spend: str | None = None, narrative: str = "") -> dict:
    payload = {
        "event_type": "performance.reported",
        "transaction_id": f"perf-{uuid7()}",
        "supplier_key": rule.supplier_key,
        "metric": rule.metric or "delivery_rate",
        "value": value,
        "narrative": narrative,
        "reported_on": "2026-06-01",
    }
    if spend is not None:
        payload["period_spend"] = {"amount": spend, "currency": "USD"}
    return payload


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"))


def agent_cases_from_response(rule: RuleIR, raw: str) -> list[TestCase]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("agent cases must be a list")
    cases: list[TestCase] = []
    for item in data:
        cases.append(
            TestCase(
                case_id=f"agent-{uuid7()}",
                rule_id=rule.rule_id,
                author="agent",
                title=item["title"],
                events=item["events"],
                expected_outcome=item["expected_outcome"],
                expected_amount=Decimal(str(item["expected_amount"])) if item.get("expected_amount") is not None else None,
            )
        )
    return cases
