"""Contract unit-test cases and evaluation results."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from glasswing_domain.money import Money


class FormulaTrace(BaseModel):
    model_config = ConfigDict(extra="allow")

    inputs: dict[str, Any] = {}
    formula: str = ""
    intermediates: dict[str, Any] = {}
    result: str = ""


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    outcome: Literal["pass", "violation", "escalate", "skipped"]
    amount_at_risk: Money | None = None
    amount_estimated: bool = False
    formula_trace: FormulaTrace = Field(default_factory=FormulaTrace)
    explanation: str = ""
    evidence_refs: list[str] = []
    model_called: bool = False


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    rule_id: str
    author: Literal["template", "agent"]
    title: str
    events: list[dict[str, Any]]
    expected_outcome: Literal["pass", "violation", "escalate", "skipped"]
    expected_amount: Decimal | None = None
    expect_model_call: bool | None = None
    cite_clause_id: str | None = None
    accept_any_judgment: bool = False

    def expected_money(self, currency: str = "USD") -> Money | None:
        if self.expected_amount is None:
            return None
        return Money(amount=self.expected_amount, currency=currency)


class TestCaseResult(BaseModel):
    case_id: str
    rule_id: str
    author: Literal["template", "agent"]
    passed: bool
    expected_outcome: str
    actual_outcome: str
    expected_amount: str | None = None
    actual_amount: str | None = None
    waived: bool = False
    waive_reason: str | None = None
    detail: str = ""


class TestReport(BaseModel):
    run_id: str
    results: list[TestCaseResult] = []

    def template_failures(self) -> list[TestCaseResult]:
        return [row for row in self.results if row.author == "template" and not row.passed]

    def blocking(self) -> list[TestCaseResult]:
        return [
            row
            for row in self.results
            if not row.passed and not row.waived and row.author == "template"
        ]
