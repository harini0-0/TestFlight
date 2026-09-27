"""Local stand-in for Bedrock. Every compile still goes through this client."""

from __future__ import annotations

import json

from glasswing_domain.ontology import Clause
from glasswing_domain.rules import RuleIR

from compiler.pipeline import compile_clause_deterministic, is_boilerplate


class RecordingModel:
    def __init__(self, supplier_key: str, model_id: str = "anthropic.claude-sonnet") -> None:
        self.supplier_key = supplier_key
        self.model_id = model_id
        self.calls: list[tuple[str, str]] = []

    def route(self, clause: Clause) -> bool:
        self.calls.append(("route", clause.clause_id))
        if is_boilerplate(clause):
            return False
        return True

    def compile_rule(self, clause: Clause) -> RuleIR | None:
        self.calls.append(("compile", clause.clause_id))
        return compile_clause_deterministic(clause, self.supplier_key)

    def author_cases(self, rule: RuleIR) -> str:
        self.calls.append(("author_cases", rule.rule_id))
        return "[]"

    def judge(self, system: str, user: str) -> str:
        self.calls.append(("judge", user[:80]))
        clause_id = "clause"
        narrative = ""
        try:
            payload = json.loads(user)
            clause_id = payload.get("clause_id", clause_id)
            narrative = json.dumps(payload.get("transaction") or {}).lower()
        except json.JSONDecodeError:
            payload = {}
            narrative = user.lower()
        failed = "did not prioritize" in narrative or "shortage" in narrative and "fail" in narrative
        if "did not prioritize" in narrative:
            outcome = "violation"
            explanation = "The performance narrative says the supplier did not prioritize the buyer."
        else:
            outcome = "pass"
            explanation = "Nothing in the transaction shows a breach of the clause."
        if failed:
            outcome = "violation"
        return json.dumps(
            {
                "outcome": outcome,
                "explanation": explanation,
                "evidence_refs": [clause_id],
                "estimated_amount": None,
            }
        )

    def investigate(self, system: str, user: str) -> str:
        self.calls.append(("investigate", "1"))
        if "tool" not in user or "transcript" in user and user.count("tool") < 2:
            if "get_clause" not in user:
                return json.dumps({"tool": "get_clause", "arguments": {}})
        return json.dumps(
            {
                "root_cause": "The invoice does not match the compiled condition.",
                "confidence": "0.8",
                "recommended_action": "Request a supplier credit.",
                "evidence_refs": ["8.2"],
                "proposed_rule_patch": None,
            }
        )
