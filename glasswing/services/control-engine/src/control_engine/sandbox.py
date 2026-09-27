"""Sandbox runs. Ephemeral ledgers never become live findings."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from glasswing_domain.evaluation import Evaluation, TestCase, TestCaseResult, TestReport
from glasswing_domain.ids import uuid7
from glasswing_domain.rules import RuleIR
from glasswing_domain.transactions import ClockTick, Invoice, PerformanceEvent, SpendEvent
from pydantic import TypeAdapter

from control_engine.evaluators import CENT
from control_engine.ledger import ZERO, evaluate_condition, natural_language_applicable

EventModel = Invoice | SpendEvent | PerformanceEvent | ClockTick
_adapter: TypeAdapter[EventModel] = TypeAdapter(EventModel)

Judge = Callable[[RuleIR, EventModel, Decimal], Evaluation]


def parse_event(payload: dict) -> EventModel:
    return _adapter.validate_python(payload)


def run_case(
    rule: RuleIR,
    case: TestCase,
    judge: Judge | None = None,
) -> tuple[TestCaseResult, list[Evaluation]]:
    balance = ZERO
    evaluations: list[Evaluation] = []
    model_calls = 0
    last: Evaluation | None = None
    for payload in case.events:
        event = parse_event(payload)
        if rule.kind == "natural_language" or rule.rule_type == "natural_language":
            if not natural_language_applicable(rule, event):
                last = Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="trigger did not match", model_called=False)
            else:
                if judge is None:
                    raise RuntimeError("natural-language case requires a judge")
                last = judge(rule, event, balance)
                if last.model_called:
                    model_calls += 1
            evaluations.append(last)
            continue
        evaluation, delta = evaluate_condition(rule, event, balance)
        balance += delta
        last = evaluation
        evaluations.append(evaluation)
    if last is None:
        last = Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="no events")
    actual_amount = last.amount_at_risk.amount if last.amount_at_risk else None
    judged = case.accept_any_judgment and last.outcome in {"pass", "violation", "escalate"}
    outcome_ok = judged or last.outcome == case.expected_outcome
    shown_expected = last.outcome if judged else case.expected_outcome
    amount_ok = True
    if case.expected_amount is not None:
        actual = actual_amount or ZERO
        amount_ok = abs(actual - case.expected_amount) <= CENT
    model_ok = True
    if case.expect_model_call is True:
        model_ok = model_calls > 0 and bool(last.evidence_refs or last.explanation)
    if case.expect_model_call is False:
        model_ok = model_calls == 0 and last.model_called is False
    cite_ok = True
    if case.cite_clause_id and case.expect_model_call:
        cite_ok = case.cite_clause_id in last.evidence_refs or case.cite_clause_id in last.explanation
    passed = outcome_ok and amount_ok and model_ok and cite_ok
    detail = last.explanation
    if not outcome_ok:
        detail = f"outcome {last.outcome} != {case.expected_outcome}"
    elif not amount_ok:
        detail = f"amount {actual_amount} != {case.expected_amount}"
    return (
        TestCaseResult(
            case_id=case.case_id,
            rule_id=rule.rule_id,
            author=case.author,
            passed=passed,
            expected_outcome=shown_expected,
            actual_outcome=last.outcome,
            expected_amount=str(case.expected_amount) if case.expected_amount is not None else None,
            actual_amount=str(actual_amount) if actual_amount is not None else None,
            detail=detail,
        ),
        evaluations,
    )


def run_suite(rules: list[RuleIR], cases: list[TestCase], judge: Judge | None = None) -> TestReport:
    by_id = {rule.rule_id: rule for rule in rules}
    results: list[TestCaseResult] = []
    for case in cases:
        rule = by_id[case.rule_id]
        result, _ = run_case(rule, case, judge)
        results.append(result)
    return TestReport(run_id=uuid7(), results=results)
