"""Practice cases must agree with the engine for the rules a compiler actually emits."""

import json
from decimal import Decimal

from compiler.recording_model import RecordingModel
from compiler.testgen import template_cases
from control_engine.sandbox import run_suite
from gateway.platform import ModelBridge
from glasswing_domain.money import Money
from glasswing_domain.ontology import Eligibility
from glasswing_domain.rules import Obligation, RuleIR, Threshold
from investigator.service import judge_natural_language


def _judge(rule, event, _balance):
    bridge = ModelBridge(RecordingModel(rule.supplier_key))
    return judge_natural_language(bridge, rule, json.loads(event.model_dump_json()), "m")


def _assert_pass(rule: RuleIR) -> None:
    cases = template_cases(rule)
    assert cases
    report = run_suite([rule], cases, _judge)
    failed = [row for row in report.results if not row.passed]
    assert not failed, [(row.expected_outcome, row.actual_outcome, row.detail) for row in failed]


def test_clock_tick_clause_is_not_tested_with_another_clock_tick():
    rule = RuleIR(
        rule_id="webpage",
        kind="natural_language",
        rule_type="natural_language",
        supplier_key="insight",
        source_clause_ids=["1.7"],
        trigger=["clock.tick"],
        clause_text="Successful Respondent shall include a current price list with its webpage.",
    )
    _assert_pass(rule)


def test_rebate_cases_use_the_category_the_rule_names():
    rule = RuleIR(
        rule_id="adobe",
        kind="condition",
        rule_type="threshold_rebate",
        supplier_key="insight",
        source_clause_ids=["c"],
        trigger=["invoice.posted", "spend.adjusted"],
        eligibility=Eligibility(include_categories=["Adobe Cumulative Licensing Program (CLP) Education"], exclude=[]),
        threshold=Threshold(amount=Decimal("100000")),
        obligation=Obligation(rate=Decimal("0.06"), application="rate_on_each_invoice_once_crossed"),
        description_key="adobe_clp_education_level_3",
    )
    _assert_pass(rule)


def test_price_case_includes_the_description_the_rule_matches():
    rule = RuleIR(
        rule_id="price",
        kind="condition",
        rule_type="price_match",
        supplier_key="insight",
        source_clause_ids=["p"],
        trigger=["invoice.posted"],
        description_key="acrobat",
        contracted_price=Money(amount=Decimal("99.44")),
        trigger_filters={"category": "software"},
    )
    _assert_pass(rule)
