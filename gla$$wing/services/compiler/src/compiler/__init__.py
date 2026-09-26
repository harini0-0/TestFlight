"""Compiler service: parse, route, compile, score, and author tests."""

from __future__ import annotations

from decimal import Decimal

from glasswing_domain.ontology import Clause
from glasswing_domain.rules import RuleIR

from compiler.pipeline import (
    compile_clause_deterministic,
    document_hash,
    hash_embed,
    is_boilerplate,
    score_rule,
    segment_clauses,
)
from compiler.testgen import template_cases

__all__ = [
    "compile_document",
    "document_hash",
    "hash_embed",
    "score_rule",
    "segment_clauses",
    "template_cases",
]


def compile_document(
    text: str,
    supplier_key: str,
    high_value_threshold: Decimal,
    model,
    on_progress=None,
) -> tuple[list[Clause], list[RuleIR], list[list[float]]]:
    """A live model exposes compile_pack(text). RecordingModel still routes clause by clause."""
    compile_pack = getattr(model, "compile_pack", None)
    if callable(compile_pack):
        clauses, raw_rules = compile_pack(text, on_progress=on_progress)
        by_id = {clause.clause_id: clause for clause in clauses}
        rules: list[RuleIR] = []
        for rule in raw_rules:
            rule = rule.model_copy(update={"supplier_key": supplier_key})
            clause = by_id.get(rule.source_clause_ids[0])
            rules.append(score_rule(rule, clause.text if clause else (rule.clause_text or ""), high_value_threshold))
        embeddings = [hash_embed(clause.text) for clause in clauses] or [hash_embed(text)]
        return clauses, rules, embeddings
    clauses = segment_clauses(text)
    embeddings = [hash_embed(clause.text) for clause in clauses]
    rules = []
    for clause in clauses:
        if is_boilerplate(clause):
            clause.commercial = False
            continue
        commercial = model.route(clause)
        clause.commercial = commercial
        if not commercial:
            continue
        compiled = model.compile_rule(clause)
        if compiled is None:
            compiled = compile_clause_deterministic(clause, supplier_key)
        if compiled is None:
            continue
        compiled = compiled.model_copy(update={"supplier_key": supplier_key})
        rules.append(score_rule(compiled, clause.text, high_value_threshold))
    return clauses, rules, embeddings
