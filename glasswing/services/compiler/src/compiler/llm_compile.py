"""Turn a document pack into Rule IR. Long packs are read in overlapping parts so nothing is dropped."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from glasswing_domain.llm_json import extract_json
from glasswing_domain.ontology import Clause
from glasswing_domain.prompts import prompt_text
from glasswing_domain.related import index_clauses, related_block
from glasswing_domain.rules import RuleIR, engine_triggers
from glasswing_domain.windows import split_text
from pydantic import ValidationError

Complete = Callable[[str, str], str]
Progress = Callable[[dict[str, Any]], None]


class CompilerFailure(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LlmCompiler:
    def __init__(self, supplier_key: str, complete: Complete, model_id: str) -> None:
        self.supplier_key = supplier_key
        self.model_id = model_id
        self._complete = complete

    def compile_pack(self, text: str, on_progress: Progress | None = None) -> tuple[list[Clause], list[RuleIR]]:
        return compile_pack_text(text, self.supplier_key, self._complete, on_progress=on_progress)


def compile_pack_text(
    text: str,
    supplier_key: str,
    complete: Complete,
    on_progress: Progress | None = None,
) -> tuple[list[Clause], list[RuleIR]]:
    parts = split_text(text)
    if not parts:
        raise CompilerFailure("the model could not produce a valid rule engine: the document was empty")
    system = _system_prompt()
    indexed = index_clauses(text)
    rules: list[RuleIR] = []
    seen: set[str] = set()
    total = len(parts)
    _report(on_progress, 0, total, f"The documents are split into {total} part{'s' if total != 1 else ''}. Each part is read in full.")
    for index, part in enumerate(parts, start=1):
        _report(on_progress, index, total, f"Reading part {index} of {total}. {len(rules)} rule{'s' if len(rules) != 1 else ''} kept so far.")
        batch_rules = _compile_part(
            system,
            supplier_key,
            complete,
            part,
            index,
            total,
            _digest(rules),
            related_block(part, indexed),
            allow_empty=total > 1,
        )
        for rule in batch_rules:
            fingerprint = _fingerprint(rule)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            rules.append(rule.model_copy(update={"rule_id": _unique_rule_id(rule.rule_id, rules)}))
    if not rules:
        raise CompilerFailure("the model could not produce a valid rule engine: no commercial rules were returned")
    _report(on_progress, total, total, f"Finished reading {total} part{'s' if total != 1 else ''}. {len(rules)} rules kept.")
    return _clauses_for(rules, None), rules


def _compile_part(
    system: str,
    supplier_key: str,
    complete: Complete,
    part: str,
    index: int,
    total: int,
    digest: str,
    related: str,
    allow_empty: bool,
) -> list[RuleIR]:
    header = (
        f"supplier_key: {supplier_key}\n"
        f"This is part {index} of {total} of one document pack.\n"
        "Extract every commercial term written in this part: discounts, rebates, thresholds, "
        "volume tiers, fees, payment terms, renewal dates, and service levels.\n"
        "Do not skip a term because it looks minor.\n"
        "Do not repeat a term listed as already captured unless this part changes the number.\n"
    )
    if related:
        header += (
            "\nRelated clauses from other parts. Use them to interpret this part. "
            "Do not emit a second copy of a rule already listed as captured.\n"
            f"{related}\n"
        )
    if digest:
        header += f"\nAlready captured:\n{digest}\n"
    user = f"{header}\nDocument part:\n{part}"
    last_error = ""
    for _attempt in range(2):
        prompt = user if not last_error else f"{user}\n\nThe previous JSON failed validation:\n{last_error}\nReturn corrected JSON only."
        try:
            raw = complete(system, prompt)
            _clauses, rules = _parse_pack(raw, supplier_key, allow_empty=allow_empty)
            return rules
        except ValueError as exc:
            last_error = _short(exc)
    raise CompilerFailure(f"the model could not produce a valid rule engine: part {index} of {total} could not be read: {last_error}")


def _report(on_progress: Progress | None, index: int, total: int, detail: str) -> None:
    if on_progress is not None:
        on_progress({"index": index, "total": total, "detail": detail})


def _digest(rules: list[RuleIR]) -> str:
    lines = []
    for rule in rules[-40:]:
        text = " ".join((rule.clause_text or rule.assertion or rule.rule_type).split())
        lines.append(f"- {rule.rule_type}: {text[:180]}")
    return "\n".join(lines)


def _fingerprint(rule: RuleIR) -> str:
    text = " ".join((rule.clause_text or "").lower().split())
    return f"{rule.rule_type}|{text[:220]}"


def _unique_rule_id(rule_id: str, existing: list[RuleIR]) -> str:
    taken = {rule.rule_id for rule in existing}
    if rule_id not in taken:
        return rule_id
    number = 2
    while f"{rule_id}-{number}" in taken:
        number += 1
    return f"{rule_id}-{number}"


def _system_prompt() -> str:
    schema = json.dumps(RuleIR.model_json_schema())
    return (
        prompt_text("compiler_system.txt")
        + "\nReturn one JSON object and nothing else, shaped as {\"rules\": [<RuleIR>, ...]}.\n"
        + "Read the whole document. Do not require numbered headings.\n"
        + "Amounts and rates are decimal strings, never JSON numbers.\n"
        + "Each rule needs rule_id, kind, rule_type, supplier_key, source_clause_ids, trigger, and clause_text.\n"
        + "trigger values are only invoice.posted, spend.adjusted, performance.reported, and clock.tick.\n"
        + "clause_text is the sentence the rule came from.\n"
        + f"RuleIR schema:\n{schema}\n"
    )


def _parse_pack(raw: str, supplier_key: str, allow_empty: bool = False) -> tuple[list[Clause], list[RuleIR]]:
    try:
        payload = extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("model output was not JSON") from exc
    raw_rules = _rule_list(payload)
    errors: list[str] = []
    rules: list[RuleIR] = []
    for index, item in enumerate(raw_rules, start=1):
        if not isinstance(item, dict):
            errors.append(f"rule {index} was not an object")
            continue
        prepared = dict(item)
        prepared.setdefault("supplier_key", supplier_key)
        if not prepared.get("rule_id"):
            prepared["rule_id"] = f"rule-{index}"
        if isinstance(prepared.get("trigger"), str):
            prepared["trigger"] = [prepared["trigger"]]
        if isinstance(prepared.get("source_clause_ids"), str):
            prepared["source_clause_ids"] = [prepared["source_clause_ids"]]
        try:
            rule = RuleIR.model_validate(prepared)
        except ValidationError as exc:
            errors.append(f"rule {index}: {_short(exc)}")
            continue
        if rule.rule_type == "threshold_rebate" and (rule.obligation is None or rule.obligation.application is None):
            if "application" not in rule.needs_confirmation:
                rule = rule.model_copy(update={"needs_confirmation": [*rule.needs_confirmation, "application"]})
        rules.append(
            rule.model_copy(
                update={
                    "supplier_key": supplier_key,
                    "trigger": engine_triggers(rule.rule_type, list(rule.trigger)),
                }
            )
        )
    if errors:
        raise ValueError("; ".join(errors))
    if not rules:
        if allow_empty:
            return [], []
        raise ValueError("no commercial rules were returned")
    supplied = payload.get("clauses") if isinstance(payload, dict) else None
    return _clauses_for(rules, supplied if isinstance(supplied, list) else None), rules


def _rule_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rules = payload.get("rules")
        if isinstance(rules, list):
            return rules
        if isinstance(rules, dict):
            return [rules]
        if "rule_type" in payload:
            return [payload]
    raise ValueError("expected a rules array")


def _clauses_for(rules: list[RuleIR], supplied: list[Any] | None) -> list[Clause]:
    parsed: dict[str, Clause] = {}
    for item in supplied or []:
        if not isinstance(item, dict):
            continue
        try:
            clause = Clause.model_validate(item)
        except ValidationError:
            continue
        parsed[clause.clause_id] = clause
    for rule in rules:
        for clause_id in rule.source_clause_ids:
            if clause_id in parsed:
                continue
            parsed[clause_id] = Clause(
                clause_id=clause_id,
                section=clause_id,
                heading=rule.rule_type,
                text=rule.clause_text or rule.assertion or clause_id,
            )
    return list(parsed.values())


def _short(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:1500]
