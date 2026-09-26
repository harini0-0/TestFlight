"""Find clauses outside a batch that it cites or shares words with."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

HEADING = re.compile(
    r"(?m)^(?:(?P<section>\d+(?:\.\d+)*)\.?\s+(?P<heading>[^\n]+)|(?P<kind>Appendix|Exhibit)\s+(?P<label>[A-Z0-9]+)\b[^\n]*)$"
)
CITE_SECTION = re.compile(r"\b(?:section|clause|paragraph)\s+(\d+(?:\.\d+)*)\b", re.I)
CITE_APPENDIX = re.compile(r"\b(?:appendix|exhibit)\s+([A-Z0-9]+)\b", re.I)
TOKEN = re.compile(r"[a-z0-9]+")
STOP = frozenset(
    "a an the of to and or for in on by as is are be shall will with from that this at it its not any all such "
    "may must into than then per each other than".split()
)
MAX_RELATED = 6
MAX_RELATED_CHARS = 2_500
SIMILARITY_CUTOFF = 0.2


@dataclass(frozen=True)
class IndexedClause:
    clause_id: str
    heading: str
    text: str
    weights: dict[str, float]


def index_clauses(text: str) -> list[IndexedClause]:
    cleaned = text.strip()
    if not cleaned:
        return []
    matches = list(HEADING.finditer(cleaned))
    if not matches:
        blocks = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        return [_clause(f"p{index}", "", block) for index, block in enumerate(blocks, start=1)]
    clauses: list[IndexedClause] = []
    if matches[0].start() > 0:
        preamble = cleaned[: matches[0].start()].strip()
        if preamble:
            clauses.append(_clause("0", "Preamble", preamble))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
        body = cleaned[start:end].strip()
        if match.group("section"):
            clause_id = match.group("section")
            heading = match.group("heading").strip()
            full = f"{heading}\n{body}".strip() if body else heading
        else:
            kind = match.group("kind")
            label = match.group("label")
            clause_id = f"{kind} {label}"
            heading = match.group(0).strip()
            full = f"{heading}\n{body}".strip() if body else heading
        clauses.append(_clause(clause_id, heading, full))
    return clauses


def related_block(window: str, clauses: list[IndexedClause]) -> str:
    """Exact sentences from other parts: citations first, then similar wording."""
    outside = [clause for clause in clauses if clause.text not in window]
    if not outside:
        return ""
    chosen: list[IndexedClause] = []
    seen: set[str] = set()

    def take(clause: IndexedClause) -> None:
        if clause.clause_id in seen or len(chosen) >= MAX_RELATED:
            return
        seen.add(clause.clause_id)
        chosen.append(clause)

    by_id = {_normalize_id(clause.clause_id): clause for clause in outside}
    for match in CITE_SECTION.finditer(window):
        cited = by_id.get(match.group(1))
        if cited:
            take(cited)
    for match in CITE_APPENDIX.finditer(window):
        label = match.group(1).upper()
        for key in (f"appendix {label}".lower(), f"exhibit {label}".lower()):
            cited = by_id.get(key)
            if cited:
                take(cited)
    queries = [part.strip() for part in re.split(r"\n\s*\n", window) if part.strip()] or [window]
    scored: list[tuple[float, IndexedClause]] = []
    for clause in outside:
        if clause.clause_id in seen:
            continue
        best = max((_cosine(_weights(query), clause.weights) for query in queries), default=0.0)
        if best >= SIMILARITY_CUTOFF:
            scored.append((best, clause))
    scored.sort(key=lambda item: item[0], reverse=True)
    for _score, clause in scored:
        take(clause)
    lines: list[str] = []
    used = 0
    for clause in chosen:
        label = clause.clause_id
        block = f"[{label}] {clause.text}"
        if used and used + len(block) > MAX_RELATED_CHARS:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


def _clause(clause_id: str, heading: str, text: str) -> IndexedClause:
    return IndexedClause(clause_id=clause_id, heading=heading, text=text, weights=_weights(text))


def _normalize_id(clause_id: str) -> str:
    return " ".join(clause_id.lower().split())


def _weights(text: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for token in TOKEN.findall(text.lower()):
        if len(token) < 3 or token in STOP:
            continue
        counts[token] = counts.get(token, 0.0) + 1.0
    norm = math.sqrt(sum(value * value for value in counts.values()))
    if norm == 0:
        return {}
    return {token: value / norm for token, value in counts.items()}


def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(weight * right.get(token, 0.0) for token, weight in left.items())
