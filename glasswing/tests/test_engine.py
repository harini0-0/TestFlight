from datetime import date
from decimal import Decimal

import pytest
from control_engine.evaluators import expected_rebate
from control_engine.ledger import evaluate_condition
from glasswing_domain.money import Money
from glasswing_domain.ontology import Eligibility, Period
from glasswing_domain.rules import Obligation, RuleIR, Threshold
from glasswing_domain.transactions import Invoice, InvoiceLine
from hypothesis import given
from hypothesis import strategies as st


def test_money_rejects_float():
    with pytest.raises(TypeError):
        Money(amount=1.5, currency="USD")


def test_unknown_ir_version_rejected():
    with pytest.raises(Exception):
        RuleIR.model_validate(
            {
                "ir_version": "9.9",
                "rule_id": "r",
                "kind": "condition",
                "rule_type": "price_match",
                "supplier_key": "acme",
                "source_clause_ids": ["1"],
                "trigger": ["invoice.posted"],
            }
        )


def _rebate(application: str) -> RuleIR:
    return RuleIR(
        rule_id="rule-8.2",
        kind="condition",
        rule_type="threshold_rebate",
        supplier_key="acme",
        source_clause_ids=["8.2"],
        trigger=["invoice.posted"],
        period=Period(),
        eligibility=Eligibility(include_categories=["goods"], exclude=["freight", "tax"]),
        threshold=Threshold(amount=Decimal("2000000"), currency="USD"),
        obligation=Obligation(rate=Decimal("0.05"), application=application),
    )


def _invoice(number: str, amount: str, rebate: str) -> Invoice:
    return Invoice(
        transaction_id=number,
        supplier_key="acme",
        invoice_number=number,
        invoice_date=date(2026, 3, 1),
        lines=[
            InvoiceLine(
                category="goods",
                quantity=Decimal("1"),
                unit_price=Money(amount=Decimal(amount), currency="USD"),
                extended_amount=Money(amount=Decimal(amount), currency="USD"),
                rebate_amount=Money(amount=Decimal(rebate), currency="USD"),
            )
        ],
    )


def test_acme_invoice_leakage_is_4200():
    rule = _rebate("rate_on_each_invoice_once_crossed")
    prior = _invoice("PRIOR", "2316000", "115800")
    first, delta = evaluate_condition(rule, prior, Decimal("0"))
    assert first.outcome == "pass"
    current = _invoice("INV-29381", "84000", "0")
    second, _ = evaluate_condition(rule, current, delta)
    assert second.outcome == "violation"
    assert second.amount_at_risk is not None
    assert second.amount_at_risk.amount == Decimal("4200.0000")
    assert "8.2" in rule.source_clause_ids


@given(
    eligible=st.decimals(min_value=1, max_value=500000, places=2, allow_nan=False, allow_infinity=False),
    rate=st.decimals(min_value="0.01", max_value="0.2", places=4, allow_nan=False, allow_infinity=False),
)
def test_rebate_leakage_matches_rate_times_eligible(eligible: Decimal, rate: Decimal):
    threshold = Decimal("100")
    expected = expected_rebate(
        "rate_on_each_invoice_once_crossed",
        rate,
        eligible,
        threshold,
        threshold,
    )
    assert expected == (rate * eligible).quantize(Decimal("0.01"))
