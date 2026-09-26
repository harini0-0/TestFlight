"""OpenAI-compatible model (DeepSeek / GLM via the hackathon's Sciforium
proxy). Used when GLASSWING_LLM=deepseek (see model_factory.build_model).

Same interface and same fail-soft philosophy as ClaudeModel — see that
module's docstring — but this backend can't rely on Anthropic-style
guaranteed structured output (Sciforium is a third-party OpenAI-compatible
proxy in front of DeepSeek/GLM; there's no guarantee it supports strict
json_schema mode), so the schema is spelled out in the prompt instead and
the response is parsed as best-effort JSON, with a markdown-fence strip
since some models wrap JSON answers in ```json even when told not to.
"""

from __future__ import annotations

import json
import os

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

DEFAULT_BASE_URL = "https://api.sciforium.com/v1"
# Sciforium's model field is the whole deployment path, not a bare model
# name — e.g. "/deployments/<TEAM_DEPLOYMENT_ID>/deepseek-ai/DeepSeek-V4.1-Flash".
# The deployment ID is per-team, so there's no universal default: set
# SCIFORIUM_DEEPSEEK_MODEL (see .env) or pass model_id explicitly.

_JSON_ONLY = "\n\nReturn ONLY a single valid JSON object matching this schema. No markdown, no explanation, no code fence.\nSchema: {schema}"


REQUEST_TIMEOUT_SECONDS = 60


def _client():
    from openai import OpenAI

    return OpenAI(
        base_url=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.environ["OPENAI_COMPATIBLE_API_KEY"],
        # Every method here already fails soft (falls back to None/True/escalate
        # on any exception), so a bounded timeout is strictly better than the
        # SDK default (10 min): one slow/hung clause degrades to a fallback
        # instead of stalling an entire multi-document pack compile.
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=1,
    )


def _strip_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


class DeepSeekModel:
    def __init__(self, supplier_key: str, model_id: str | None = None, client=None) -> None:
        self.supplier_key = supplier_key
        self.model_id = model_id or os.environ.get("SCIFORIUM_DEEPSEEK_MODEL")
        if not self.model_id and client is None:
            raise RuntimeError(
                "DeepSeekModel needs a model_id — set SCIFORIUM_DEEPSEEK_MODEL to the full "
                "deployment path (e.g. /deployments/<TEAM_DEPLOYMENT_ID>/deepseek-ai/DeepSeek-V4.1-Flash)"
            )
        self.client = client or _client()
        self.calls: list[tuple[str, str]] = []

    def _complete_json(self, system: str, user: str, schema_cls):
        # DeepSeek V4.1 Flash is a reasoning model: it spends part of
        # max_tokens on a separate reasoning_content field before writing the
        # final answer into content. A too-small budget can burn through
        # reasoning tokens and get cut off (finish_reason="length") before
        # any JSON is written at all, so this needs real headroom.
        schema_hint = _JSON_ONLY.format(schema=json.dumps(schema_cls.model_json_schema()))
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system + schema_hint},
                {"role": "user", "content": user},
            ],
            max_tokens=4000,
            temperature=0,
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        if choice.finish_reason == "length" and not text.strip():
            raise ValueError("truncated before any content was written (max_tokens too small)")
        return schema_cls.model_validate_json(_strip_fence(text))

    # -- Layer 1: compiler -------------------------------------------------

    def route(self, clause: Clause) -> bool:
        self.calls.append(("route", clause.clause_id))
        if is_boilerplate(clause):
            return False
        try:
            result = self._complete_json(
                ROUTE_SYSTEM_PROMPT,
                f"[{clause.section}] {clause.heading}\n{clause.text}",
                ClauseRoute,
            )
            return result.commercial
        except Exception:
            return True

    def compile_rule(self, clause: Clause) -> RuleIR | None:
        self.calls.append(("compile", clause.clause_id))
        try:
            extraction = self._complete_json(
                prompt_text("compiler_system.txt"),
                f"[{clause.section}] {clause.heading}\n{clause.text}",
                RuleExtraction,
            )
        except Exception:
            return None

        if not extraction.applicable:
            return None

        return build_rule_from_extraction(self.supplier_key, clause, extraction)

    def author_cases(self, rule: RuleIR) -> str:
        self.calls.append(("author_cases", rule.rule_id))
        try:
            result = self._complete_json(prompt_text("test_agent.txt"), rule.model_dump_json(), AgentCasesOutput)
            return json.dumps([case.model_dump() for case in result.cases])
        except Exception:
            return "[]"

    # -- Layer 2/3: natural-language judging + investigation ---------------

    def judge(self, system: str, user: str) -> str:
        self.calls.append(("judge", user[:80]))
        try:
            result = self._complete_json(system, user, NlJudgmentOutput)
            return result.model_dump_json()
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
            result = self._complete_json(system, user, InvestigationStep)
            return result.model_dump_json()
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
