"""Natural-language judgments and condition-rule investigations."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from glasswing_domain.evaluation import Evaluation, FormulaTrace
from glasswing_domain.money import Money
from glasswing_domain.rules import RuleIR


class LlmClient(Protocol):
    def complete(self, *, model_id: str, system: str, user: str, schema_name: str) -> str: ...


def _money_amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "").replace("$", ""))
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    na = sum(a * a for a in left) ** 0.5
    nb = sum(b * b for b in right) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search_clauses(
    query: list[float],
    rows: list[dict[str, Any]],
    tenant_id: str,
    contract_id: str | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        if row["tenant_id"] != tenant_id:
            continue
        if contract_id and row.get("document_id") not in (None, contract_id):
            continue
        scored.append((cosine(query, row["embedding"]), row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in scored[:limit]]


def judge_natural_language(llm: LlmClient, rule: RuleIR, event_payload: dict, model_id: str) -> Evaluation:
    from glasswing_domain.prompts import prompt_text

    user = json.dumps(
        {
            "clause_id": rule.source_clause_ids[0],
            "clause_text": rule.clause_text,
            "decision": rule.decision_prompt,
            "transaction": event_payload,
        }
    )
    raw = llm.complete(
        model_id=model_id,
        system=prompt_text("nl_judge.txt"),
        user=user,
        schema_name="NlJudgment",
    )
    data = json.loads(raw)
    amount = None
    estimated = False
    parsed_amount = _money_amount(data.get("estimated_amount"))
    if parsed_amount is not None:
        amount = Money(amount=parsed_amount, currency="USD")
        estimated = True
    return Evaluation(
        rule_id=rule.rule_id,
        outcome=data["outcome"],
        amount_at_risk=amount,
        amount_estimated=estimated,
        formula_trace=FormulaTrace(formula="natural-language judgment", result=data.get("explanation", "")),
        explanation=data.get("explanation", ""),
        evidence_refs=list(data.get("evidence_refs") or rule.source_clause_ids),
        model_called=True,
    )


def investigate_exception(
    llm: LlmClient,
    evidence: dict,
    model_id: str,
    tools: dict[str, Any],
) -> dict[str, Any]:
    """Tool loop is capped. Tools are closures already bound to the tenant."""
    from glasswing_domain.prompts import prompt_text

    transcript = [{"role": "evidence", "content": evidence}]
    rounds = 0
    final: dict[str, Any] | None = None
    while rounds < 4:
        rounds += 1
        raw = llm.complete(
            model_id=model_id,
            system=prompt_text("investigator_system.txt"),
            user=json.dumps({"transcript": transcript, "tools": list(tools)}),
            schema_name="Investigation",
        )
        data = json.loads(raw)
        if data.get("tool"):
            name = data["tool"]
            if name not in tools:
                transcript.append({"role": "tool_error", "content": "unknown tool"})
                continue
            transcript.append({"role": "tool", "name": name, "content": tools[name](data.get("arguments") or {})})
            continue
        final = data
        break
    if final is None:
        final = {
            "root_cause": "investigator did not finish",
            "confidence": "0",
            "recommended_action": "review the deterministic trace",
            "evidence_refs": evidence.get("clause_ids", []),
        }
    final["rounds"] = rounds
    return final
