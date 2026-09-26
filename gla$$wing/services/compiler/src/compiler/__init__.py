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
) -> tuple[list[Clause], list[RuleIR], list[list[float]]]:
    """model.route(clause) -> bool, model.compile_rule(clause) -> RuleIR | None."""
    clauses = segment_clauses(text)
    embeddings = [hash_embed(clause.text) for clause in clauses]
    rules: list[RuleIR] = []
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
