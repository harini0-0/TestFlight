import json
from decimal import Decimal

import httpx
from compiler.llm_compile import CompilerFailure, LlmCompiler
from control_engine.ledger import evaluate_condition
from glasswing_adapters.llm import MODEL_ID, ChatClient
from glasswing_domain.money import Money
from glasswing_domain.ontology import Eligibility
from glasswing_domain.rules import Obligation, RuleIR, Threshold
from ingestion.normalize import normalize_unstructured

from compiler import compile_document

PROSE = (
    "Acme will give the buyer a rebate of 5% on annual purchases exceeding $2,000,000. "
    "The rebate is calculated on eligible goods."
)

RULE = {
    "rule_id": "rule-rebate",
    "kind": "condition",
    "rule_type": "threshold_rebate",
    "supplier_key": "acme",
    "source_clause_ids": ["rebate-1"],
    "trigger": ["invoice.posted", "spend.adjusted"],
    "assertion": "rebated_amount_matches_obligation",
    "needs_confirmation": ["application"],
    "threshold": {"metric": "eligible_spend", "op": "gte", "amount": "2000000", "currency": "USD"},
    "obligation": {"rate": "0.05", "application": None},
    "eligibility": {"include_categories": ["goods"], "exclude": ["freight", "tax"]},
    "clause_text": "5% rebate on annual purchases exceeding $2,000,000",
    "period": {"type": "contract_year", "anchor": "effective_date"},
}

INVOICE = {
    "events": [
        {
            "event_type": "invoice.posted",
            "transaction_id": "INV-29381",
            "supplier_key": "acme",
            "invoice_number": "INV-29381",
            "invoice_date": "2026-04-01",
            "currency": "USD",
            "lines": [
                {
                    "sku": "Widget A",
                    "description": "Widget A",
                    "category": "goods",
                    "quantity": "8400",
                    "unit_price": {"amount": "10", "currency": "USD"},
                    "extended_amount": {"amount": "84000", "currency": "USD"},
                    "rebate_amount": {"amount": "0", "currency": "USD"},
                }
            ],
        }
    ]
}


def _envelope(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _client(handler) -> ChatClient:
    return ChatClient(api_key="test-key", base_url="https://llm.example", transport=httpx.MockTransport(handler))


def test_sciforium_base_url_keeps_the_v1_prefix():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_envelope({"rules": [RULE]}))

    ChatClient(
        api_key="test-key",
        base_url="https://api.sciforium.com/v1",
        transport=httpx.MockTransport(handler),
    ).complete("system", "user")
    assert seen["url"] == "https://api.sciforium.com/v1/chat/completions"


def test_prose_contract_compiles_through_the_model():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        body = json.loads(request.content)
        seen["model"] = body["model"]
        seen["temperature"] = body["temperature"]
        seen["response_format"] = body["response_format"]
        return httpx.Response(200, json=_envelope({"rules": [RULE]}))

    model = LlmCompiler("acme", _client(handler).complete, MODEL_ID)
    _clauses, rules, _embeddings = compile_document(PROSE, "acme", Decimal("100000"), model)
    rebate = rules[0]
    assert seen["url"] == "https://llm.example/chat/completions"
    assert seen["authorization"] == "Bearer test-key"
    assert seen["model"] == MODEL_ID
    assert seen["temperature"] == 0
    assert seen["response_format"] == {"type": "json_object"}
    assert rebate.rule_type == "threshold_rebate"
    assert rebate.threshold is not None
    assert rebate.threshold.amount == Decimal("2000000")
    assert rebate.obligation is not None
    assert rebate.obligation.rate == Decimal("0.05")
    assert "application" in rebate.needs_confirmation


def test_model_trigger_names_are_rewritten_to_engine_events():
    price = {
        "rule_id": "rule-price",
        "kind": "condition",
        "rule_type": "price_match",
        "supplier_key": "acme",
        "source_clause_ids": ["price-1"],
        "trigger": ["invoice_line"],
        "sku": "Widget A",
        "contracted_price": {"amount": "10", "currency": "USD"},
        "clause_text": "Widget A unit price is $10",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope({"rules": [price]}))

    model = LlmCompiler("acme", _client(handler).complete, MODEL_ID)
    _clauses, rules, _embeddings = compile_document("Widget A unit price is $10.", "acme", Decimal("100000"), model)
    assert rules[0].trigger == ["invoice.posted"]


def test_compiler_retries_invalid_json_once():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_envelope({"rules": [{"nope": True}]}))
        return httpx.Response(200, json=_envelope({"rules": [RULE]}))

    model = LlmCompiler("acme", _client(handler).complete, MODEL_ID)
    _clauses, rules, _embeddings = compile_document(PROSE, "acme", Decimal("100000"), model)
    assert calls["n"] == 2
    assert rules[0].rule_type == "threshold_rebate"


def test_compiler_failure_after_two_invalid_replies():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope({"rules": []}))

    model = LlmCompiler("acme", _client(handler).complete, MODEL_ID)
    try:
        compile_document(PROSE, "acme", Decimal("100000"), model)
    except CompilerFailure as exc:
        assert "valid rule engine" in exc.detail
    else:
        raise AssertionError("expected a compiler failure")


def test_prose_invoice_is_structured_for_the_engine():
    prose = "Invoice INV-29381 from Acme dated April 1 2026. Widget A, 8400 units at $10, extended $84,000, rebate $0."

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://llm.example/chat/completions"
        return httpx.Response(200, json=_envelope(INVOICE))

    events = normalize_unstructured(prose, _client(handler).complete, "acme")
    invoice = events[0]
    assert invoice.transaction_id == "INV-29381"
    assert invoice.supplier_key == "acme"
    rule = RuleIR(
        rule_id="rule-rebate",
        kind="condition",
        rule_type="threshold_rebate",
        supplier_key="acme",
        source_clause_ids=["rebate-1"],
        trigger=["invoice.posted"],
        threshold=Threshold(amount=Decimal("2000000"), currency="USD"),
        obligation=Obligation(rate=Decimal("0.05"), application="rate_on_each_invoice_once_crossed"),
        eligibility=Eligibility(include_categories=["goods"], exclude=["freight", "tax"]),
        value_amount=Money(amount=Decimal("2000000"), currency="USD"),
    )
    evaluation, _eligible = evaluate_condition(rule, invoice, Decimal("2400000"))
    assert evaluation.outcome == "violation"
    assert evaluation.amount_at_risk is not None
    assert evaluation.amount_at_risk.amount == Decimal("4200.0000")
