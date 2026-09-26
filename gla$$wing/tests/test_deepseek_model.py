"""Offline tests for DeepSeekModel and its GLASSWING_LLM=deepseek switch.

No network access and no Sciforium key needed: the OpenAI client is
replaced with a fake returning canned chat-completion text, so these prove
the wiring (prompt in, RuleIR/JSON shape out — including the ```json fence
stripping some models add despite being told not to) rather than the actual
model's judgment.
"""

from __future__ import annotations

import json
from decimal import Decimal

from compiler.deepseek_model import DeepSeekModel
from compiler.llm_schemas import InvestigationStep, NlJudgmentOutput, RuleExtraction
from compiler.model_factory import build_model
from glasswing_domain.ontology import Clause
from glasswing_domain.rules import RuleIR


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)
        self.finish_reason = "stop"


class _ChatResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _FakeCompletions:
    def __init__(self, responder) -> None:
        # responder(system, user) -> text (already JSON, or fenced JSON)
        self._responder = responder
        self.calls: list[dict] = []

    def create(self, *, model, messages, max_tokens, temperature):
        system, user = messages[0]["content"], messages[1]["content"]
        self.calls.append({"model": model, "system": system, "user": user})
        return _ChatResponse(self._responder(system, user))


class _FakeChat:
    def __init__(self, responder) -> None:
        self.completions = _FakeCompletions(responder)


class FakeOpenAI:
    def __init__(self, responder) -> None:
        self.chat = _FakeChat(responder)


class _RaisingCompletions:
    def create(self, **kwargs):
        raise RuntimeError("simulated API failure")


class RaisingOpenAI:
    def __init__(self) -> None:
        self.chat = type("chat", (), {"completions": _RaisingCompletions()})()


REBATE_CLAUSE = Clause(
    clause_id="8.2",
    section="8.2",
    heading="Rebate",
    text=(
        "Supplier will provide a 5% rebate on annual purchases exceeding $2 million, "
        "calculated on aggregate eligible purchases during the contract year."
    ),
)

PREAMBLE_CLAUSE = Clause(clause_id="0", section="0", heading="Preamble", text="MASTER SUPPLY AGREEMENT")


def _model(responder) -> DeepSeekModel:
    return DeepSeekModel("acme", client=FakeOpenAI(responder))


def test_route_skips_boilerplate_without_calling_the_model():
    fake = FakeOpenAI(lambda *_: (_ for _ in ()).throw(AssertionError("should not be called")))
    model = DeepSeekModel("acme", client=fake)
    assert model.route(PREAMBLE_CLAUSE) is False
    assert fake.chat.completions.calls == []


def test_route_parses_plain_json():
    model = _model(lambda system, user: json.dumps({"commercial": True}))
    assert model.route(REBATE_CLAUSE) is True


def test_route_strips_markdown_fence_some_models_add_anyway():
    model = _model(lambda system, user: "```json\n" + json.dumps({"commercial": True}) + "\n```")
    assert model.route(REBATE_CLAUSE) is True


def test_route_falls_back_to_true_on_api_failure():
    model = DeepSeekModel("acme", client=RaisingOpenAI())
    assert model.route(REBATE_CLAUSE) is True


def test_compile_rule_builds_threshold_rebate():
    def responder(system, user):
        return json.dumps(
            RuleExtraction(
                applicable=True,
                kind="condition",
                rule_type="threshold_rebate",
                trigger=["invoice.posted", "spend.adjusted"],
                severity="high",
                needs_confirmation=["application"],
                threshold_amount="2000000",
                obligation_rate="0.05",
            ).model_dump()
        )

    rule = _model(responder).compile_rule(REBATE_CLAUSE)
    assert isinstance(rule, RuleIR)
    assert rule.rule_type == "threshold_rebate"
    assert rule.threshold.amount == Decimal("2000000")
    assert rule.obligation.rate == Decimal("0.05")
    assert "application" in rule.needs_confirmation


def test_compile_rule_returns_none_on_malformed_json():
    model = _model(lambda system, user: "not json at all")
    assert model.compile_rule(REBATE_CLAUSE) is None


def test_compile_rule_returns_none_when_not_applicable():
    model = _model(
        lambda s, u: json.dumps(
            RuleExtraction(applicable=False, kind="condition", rule_type="natural_language").model_dump()
        )
    )
    assert model.compile_rule(REBATE_CLAUSE) is None


def test_judge_returns_valid_json():
    model = _model(
        lambda s, u: json.dumps(
            NlJudgmentOutput(outcome="violation", explanation="did not prioritize the buyer", evidence_refs=["9.1"]).model_dump()
        )
    )
    data = json.loads(model.judge("system prompt", "user payload"))
    assert data["outcome"] == "violation"


def test_judge_falls_back_to_escalate_on_api_failure():
    model = DeepSeekModel("acme", client=RaisingOpenAI())
    data = json.loads(model.judge("system prompt", "user payload"))
    assert data["outcome"] == "escalate"


def test_investigate_tool_call_shape():
    model = _model(lambda s, u: json.dumps(InvestigationStep(tool="get_clause", arguments={}).model_dump()))
    data = json.loads(model.investigate("system prompt", "user payload"))
    assert data["tool"] == "get_clause"


def test_build_model_switches_to_deepseek(monkeypatch):
    monkeypatch.setenv("GLASSWING_LLM", "deepseek")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "test-key")
    monkeypatch.setenv("SCIFORIUM_DEEPSEEK_MODEL", "/deployments/test/deepseek-ai/DeepSeek-V4.1-Flash")
    assert isinstance(build_model("acme"), DeepSeekModel)
