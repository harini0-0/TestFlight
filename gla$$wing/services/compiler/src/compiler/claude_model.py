"""Real Claude-backed model. Used when GLASSWING_LLM=claude (see model_factory.build_model).

Matches RecordingModel's exact interface (route, compile_rule, author_cases,
judge, investigate) so it's a drop-in replacement wherever
`RecordingModel(supplier_key, ...)` is constructed in gateway.platform —
compile_document(), ModelBridge, and investigator.service all keep working
unchanged. Every method fails soft: a broken/unreachable API call falls back
to "let the deterministic pipeline decide" rather than crashing the request,
because compile_document() already retries with compile_clause_deterministic
whenever compile_rule() returns None.

Schemas and RuleIR-building logic live in llm_schemas.py, shared with
DeepSeekModel (GLASSWING_LLM=deepseek) so both backends build rules the same
way from the same extraction shape.
"""

from __future__ import annotations

import json

import anthropic
from glasswing_domain.ontology import Clause
from glasswing_domain.prompts import prompt_text
from glasswing_domain.rules import RuleIR

from compiler.llm_schemas import (
    ROUTE_SYSTEM_PROMPT,
    AgentCasesOutput,
    ClauseRoute,
    InvestigationStep,
    NlJudgmentOutput,
    RuleExtraction,
    build_rule_from_extraction,
)
from compiler.pipeline import is_boilerplate

DEFAULT_MODEL_ID = "claude-sonnet-5"

# Bundles record Bedrock-style ids (e.g. "anthropic.claude-sonnet") for
# provenance/audit; translate to a real Anthropic API model id for the
# actual call so callers don't have to know which backend is active.
_MODEL_MAP = {
    "anthropic.claude-sonnet": "claude-sonnet-5",
    "anthropic.claude-haiku": "claude-haiku-4-5",
}


def _resolve_model_id(model_id: str) -> str:
    return _MODEL_MAP.get(model_id, model_id or DEFAULT_MODEL_ID)


REQUEST_TIMEOUT_SECONDS = 60


class ClaudeModel:
    def __init__(
        self,
        supplier_key: str,
        model_id: str = "anthropic.claude-sonnet",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.supplier_key = supplier_key
        self.model_id = model_id
        # Every method here already fails soft (falls back to None/True/escalate
        # on any exception), so a bounded timeout is strictly better than the
        # SDK default (10 min): one slow clause degrades to a fallback instead
        # of stalling an entire multi-document pack compile.
        self.client = client or anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1)
        self.calls: list[tuple[str, str]] = []

    # -- Layer 1: compiler -------------------------------------------------

    def route(self, clause: Clause) -> bool:
        self.calls.append(("route", clause.clause_id))
        if is_boilerplate(clause):
            return False
        try:
            response = self.client.messages.parse(
                model=_resolve_model_id(self.model_id),
                max_tokens=200,
                output_config={"effort": "low"},
                system=ROUTE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"[{clause.section}] {clause.heading}\n{clause.text}"}],
                output_format=ClauseRoute,
            )
            return response.parsed_output.commercial
        except Exception:
            # Let the deterministic pipeline have a look rather than silently
            # dropping the clause on an API hiccup.
            return True

    def compile_rule(self, clause: Clause) -> RuleIR | None:
        self.calls.append(("compile", clause.clause_id))
        try:
            response = self.client.messages.parse(
                model=_resolve_model_id(self.model_id),
                max_tokens=1500,
                output_config={"effort": "medium"},
                system=prompt_text("compiler_system.txt"),
                messages=[{"role": "user", "content": f"[{clause.section}] {clause.heading}\n{clause.text}"}],
                output_format=RuleExtraction,
            )
            extraction = response.parsed_output
        except Exception:
            return None

        if not extraction.applicable:
            return None

        return build_rule_from_extraction(self.supplier_key, clause, extraction)

    def author_cases(self, rule: RuleIR) -> str:
        self.calls.append(("author_cases", rule.rule_id))
        try:
            response = self.client.messages.parse(
                model=_resolve_model_id(self.model_id),
                max_tokens=1500,
                output_config={"effort": "low"},
                system=prompt_text("test_agent.txt"),
                messages=[{"role": "user", "content": rule.model_dump_json()}],
                output_format=AgentCasesOutput,
            )
            return json.dumps([case.model_dump() for case in response.parsed_output.cases])
        except Exception:
            return "[]"

    # -- Layer 2/3: natural-language judging + investigation ---------------
    # These are invoked through ModelBridge, which forwards the exact
    # system/user strings investigator.service already builds (from
    # nl_judge.txt / investigator_system.txt). We only need to complete them
    # and hand back JSON text — using structured output here (rather than a
    # bare text completion) means the JSON is always valid, whereas the
    # brittle path of hoping the model returns parseable text on the first
    # try was the failure mode this class exists to remove.

    def judge(self, system: str, user: str) -> str:
        self.calls.append(("judge", user[:80]))
        try:
            response = self.client.messages.parse(
                model=_resolve_model_id(self.model_id),
                max_tokens=1000,
                output_config={"effort": "medium"},
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=NlJudgmentOutput,
            )
            return response.parsed_output.model_dump_json()
        except Exception as exc:
            return json.dumps(
                {
                    "outcome": "escalate",
                    "explanation": f"judgment call failed, needs human review: {exc}",
                    "evidence_refs": [],
                    "estimated_amount": None,
                }
            )

    def investigate(self, system: str, user: str) -> str:
        self.calls.append(("investigate", "1"))
        try:
            response = self.client.messages.parse(
                model=_resolve_model_id(self.model_id),
                max_tokens=1000,
                output_config={"effort": "medium"},
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=InvestigationStep,
            )
            return response.parsed_output.model_dump_json()
        except Exception as exc:
            return json.dumps(
                {
                    "root_cause": f"investigation call failed: {exc}",
                    "confidence": "0",
                    "recommended_action": "review the deterministic trace",
                    "evidence_refs": [],
                    "proposed_rule_patch": None,
                }
            )
