"""Offline tests for ClaudeModel and the GLASSWING_LLM switch.

No network access and no ANTHROPIC_API_KEY needed: the Anthropic client is
replaced with a fake that returns canned structured-output objects, so these
prove the wiring (request shape in, RuleIR/JSON shape out) rather than
Claude's actual judgment — that part still needs a live key + credits to
verify, per the earlier manual check against tests/golden/acme_contract.txt.
"""

from __future__ import annotations

import json
from decimal import Decimal

from compiler.claude_model import ClaudeModel
from compiler.llm_schemas import (
    ClauseRoute,
    DiscountTierExtraction,
    InvestigationStep,
    NlJudgmentOutput,
    RuleExtraction,
)
from compiler.model_factory import build_model
from compiler.recording_model import RecordingModel
from glasswing_domain.ontology import Clause
from glasswing_domain.rules import RuleIR

from compiler import compile_document


class _FakeResponse:
    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _FakeMessages:
    def __init__(self, responder):
        # responder(output_format_cls, user_content) -> parsed_output instance
        self._responder = responder
        self.calls: list[dict] = []

    def parse(self, *, model, max_tokens, output_config, system, messages, output_format):
        user_content = messages[0]["content"]
        self.calls.append({"model": model, "system": system, "user": user_content, "schema": output_format.__name__})
        return _FakeResponse(self._responder(output_format, user_content))


class FakeAnthropic:
    def __init__(self, responder):
        self.messages = _FakeMessages(responder)


class _RaisingMessages:
    def parse(self, **kwargs):
        raise RuntimeError("simulated API failure")


class RaisingAnthropic:
    def __init__(self) -> None:
        self.messages = _RaisingMessages()


REBATE_CLAUSE = Clause(
    clause_id="8.2",
    section="8.2",
    heading="Rebate",
    text=(
        "Supplier will provide a 5% rebate on annual purchases exceeding $2 million, "
        "calculated on aggregate eligible purchases during the contract year."
    ),
)

PREAMBLE_CLAUSE = Clause(
    clause_id="0",
    section="0",
    heading="Preamble",
    text="MASTER SUPPLY AGREEMENT\nSupplier: Acme",
)


def _model(responder) -> ClaudeModel:
    return ClaudeModel("acme", client=FakeAnthropic(responder))


# -- route() -----------------------------------------------------------------


def test_route_skips_boilerplate_without_calling_the_model():
    fake = FakeAnthropic(lambda *_: (_ for _ in ()).throw(AssertionError("should not be called")))
    model = ClaudeModel("acme", client=fake)
    assert model.route(PREAMBLE_CLAUSE) is False
    assert fake.messages.calls == []


def test_route_calls_model_for_non_boilerplate_clause():
    model = _model(lambda schema, _user: ClauseRoute(commercial=True))
    assert model.route(REBATE_CLAUSE) is True
    assert model.calls == [("route", "8.2")]


def test_route_falls_back_to_true_on_api_failure():
    model = ClaudeModel("acme", client=RaisingAnthropic())
    assert model.route(REBATE_CLAUSE) is True


# -- compile_rule() ------------------------------------------------------------


def test_compile_rule_builds_threshold_rebate_matching_the_deterministic_shape():
    def responder(schema, _user):
        assert schema is RuleExtraction
        return RuleExtraction(
            applicable=True,
            kind="condition",
            rule_type="threshold_rebate",
            trigger=["invoice.posted", "spend.adjusted"],
            severity="high",
            needs_confirmation=["application"],
            threshold_amount="2000000",
            threshold_currency="USD",
            obligation_rate="0.05",
            eligibility_include_categories=["goods"],
            eligibility_exclude=["freight", "tax"],
        )

    model = _model(responder)
    rule = model.compile_rule(REBATE_CLAUSE)

    assert isinstance(rule, RuleIR)
    assert rule.rule_type == "threshold_rebate"
    assert rule.source_clause_ids == ["8.2"]
    assert rule.threshold.amount == Decimal("2000000")
    assert rule.obligation.rate == Decimal("0.05")
    assert rule.obligation.application is None
    assert "application" in rule.needs_confirmation
    assert rule.eligibility.exclude == ["freight", "tax"]


def test_compile_rule_volume_discount_tiers():
    def responder(_schema, _user):
        return RuleExtraction(
            applicable=True,
            kind="condition",
            rule_type="volume_discount",
            trigger=["invoice.posted"],
            sku="Widget B",
            contracted_price_amount="10",
            tiers=[
                DiscountTierExtraction(min_qty="1000", discount_rate="0.05"),
                DiscountTierExtraction(min_qty="5000", discount_rate="0.10"),
            ],
        )

    rule = _model(responder).compile_rule(REBATE_CLAUSE)
    assert rule.rule_type == "volume_discount"
    assert [t.min_qty for t in rule.tiers] == [Decimal("1000"), Decimal("5000")]
    assert [t.discount_rate for t in rule.tiers] == [Decimal("0.05"), Decimal("0.10")]


def test_compile_rule_returns_none_when_not_applicable():
    model = _model(lambda *_: RuleExtraction(applicable=False, kind="condition", rule_type="natural_language"))
    assert model.compile_rule(REBATE_CLAUSE) is None


def test_compile_rule_returns_none_on_api_failure_so_deterministic_fallback_can_run():
    model = ClaudeModel("acme", client=RaisingAnthropic())
    assert model.compile_rule(REBATE_CLAUSE) is None


# -- judge() / investigate() ---------------------------------------------------


def test_judge_returns_valid_json_for_the_schema_investigator_expects():
    model = _model(
        lambda schema, _user: NlJudgmentOutput(
            outcome="violation", explanation="did not prioritize the buyer", evidence_refs=["9.1"]
        )
    )
    data = json.loads(model.judge("system prompt", "user payload"))
    assert data == {
        "outcome": "violation",
        "explanation": "did not prioritize the buyer",
        "evidence_refs": ["9.1"],
        "estimated_amount": None,
    }


def test_judge_discards_non_numeric_estimated_amount_instead_of_crashing_later():
    """Regression: investigator.service.judge_natural_language does
    Decimal(str(data["estimated_amount"])) with no guard downstream — a model
    returning free text here ("N/A", "5% of shortfall", ...) must be cleaned
    up to None by NlJudgmentOutput's validator, not allowed through to crash
    that call with decimal.InvalidOperation (a real 500 hit live against
    DeepSeek)."""
    for junk in ("N/A", "unknown", "approximately $500"):
        result = NlJudgmentOutput(outcome="violation", explanation="x", estimated_amount=junk)
        assert result.estimated_amount is None, f"{junk!r} should have been cleaned to None"
    # a genuine numeric string must survive untouched
    assert NlJudgmentOutput(outcome="violation", explanation="x", estimated_amount="4200.00").estimated_amount == "4200.00"


def test_judge_falls_back_to_escalate_on_api_failure():
    model = ClaudeModel("acme", client=RaisingAnthropic())
    data = json.loads(model.judge("system prompt", "user payload"))
    assert data["outcome"] == "escalate"


def test_investigate_tool_call_shape():
    model = _model(lambda schema, _user: InvestigationStep(tool="get_clause", arguments={}))
    data = json.loads(model.investigate("system prompt", "user payload"))
    assert data["tool"] == "get_clause"
    assert data["root_cause"] is None


def test_investigate_final_answer_shape():
    model = _model(
        lambda schema, _user: InvestigationStep(
            root_cause="invoice does not match the compiled condition",
            confidence="0.8",
            recommended_action="Request a supplier credit.",
            evidence_refs=["8.2"],
        )
    )
    data = json.loads(model.investigate("system prompt", "user payload"))
    assert data["tool"] is None
    assert data["root_cause"] == "invoice does not match the compiled condition"


# -- model_factory --------------------------------------------------------------


def test_build_model_defaults_to_recording_model(monkeypatch):
    monkeypatch.delenv("GLASSWING_LLM", raising=False)
    assert isinstance(build_model("acme"), RecordingModel)


def test_build_model_switches_to_claude_model(monkeypatch):
    monkeypatch.setenv("GLASSWING_LLM", "claude")
    assert isinstance(build_model("acme"), ClaudeModel)


# -- full pipeline parity with the deterministic path --------------------------


def test_compile_document_through_claude_model_matches_deterministic_shape():
    """Same acme_contract.txt clauses test_acme_flow.py compiles deterministically,
    driven instead by a ClaudeModel whose fake client answers per clause heading."""

    from pathlib import Path

    text = Path("tests/golden/acme_contract.txt").read_text(encoding="utf-8")

    def responder(schema, user_content):
        if schema is ClauseRoute:
            return ClauseRoute(commercial="Governing Law" not in user_content)
        assert schema is RuleExtraction
        if "Rebate" in user_content:
            return RuleExtraction(
                applicable=True,
                kind="condition",
                rule_type="threshold_rebate",
                trigger=["invoice.posted", "spend.adjusted"],
                severity="high",
                needs_confirmation=["application"],
                threshold_amount="2000000",
                obligation_rate="0.05",
            )
        if "Price" in user_content:
            return RuleExtraction(
                applicable=True,
                kind="condition",
                rule_type="price_match",
                trigger=["invoice.posted"],
                sku="Widget A",
                contracted_price_amount="10.00",
            )
        if "Efforts" in user_content:
            return RuleExtraction(
                applicable=True,
                kind="natural_language",
                rule_type="natural_language",
                trigger=["performance.reported"],
                decision_prompt="Did the supplier fail to prioritize the buyer during a shortage?",
                severity="medium",
            )
        return RuleExtraction(applicable=False, kind="condition", rule_type="natural_language")

    model = ClaudeModel("acme", client=FakeAnthropic(responder))
    clauses, rules, _embeddings = compile_document(text, "acme", Decimal("100000"), model)

    rebate = next(r for r in rules if r.rule_type == "threshold_rebate")
    assert rebate.source_clause_ids == ["8.2"]
    assert rebate.threshold.amount == Decimal("2000000")
    assert rebate.obligation.rate == Decimal("0.05")
    assert "application" in rebate.needs_confirmation
    assert rebate.value_band == "high"  # score_rule() still runs downstream, same as the deterministic path
    assert rebate.risk_band == "high"

    price = next(r for r in rules if r.rule_type == "price_match")
    assert price.sku == "Widget A"
    assert price.contracted_price.amount == Decimal("10.0000")

    assert any(r.rule_type == "natural_language" for r in rules)
    # Governing Law (section 12) is routed non-commercial by our fake, so no rule is generated for it
    assert not any(rule.source_clause_ids == ["12"] for rule in rules)
    governing_law = next(c for c in clauses if c.clause_id == "12")
    assert governing_law.commercial is False
