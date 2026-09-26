"""Clause cross-reference detection for the workspace clause-network view.

A pack combines several documents (master agreement, rebate schedule, price
schedule, ...) into one engine. Contracts routinely point at each other -
"the attached price schedule", "outside the rebate base", "this schedule sits
on top of the annual goods rebate". Those links are lost once the documents are
flattened. This module recovers them, deterministically, so a reviewer can see
that editing one clause may strand another.

Only cross-document references are emitted: a clause never links inside its own
document. References resolve in three ways, most trustworthy first:

1. specific  - the clause names another document by its title or filename
               ("annual goods rebate", "price schedule").
2. generic   - the clause uses a curated multi-word term for a document *kind*
               ("rebate base", "service level"); it links to the primary
               document of that kind.
3. external  - the clause cites an instrument that is not in the pack
               ("Exhibit A", "Schedule 3"); it links to an external marker.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, TypedDict

# Curated, multi-word only. Single words like "rebate" or "discount" appear too
# often in unrelated prose (an early-payment "discount") to link on safely.
KIND_GENERICS: dict[str, list[str]] = {
    "contract": ["master agreement", "master supply agreement", "master services agreement", "the agreement", "this agreement"],
    "rebate": ["rebate base", "rebate schedule", "annual rebate", "rebate program"],
    "discount": ["discount schedule", "volume discount", "volume discounts"],
    "sla": ["service level", "service levels", "delivery rate", "on time delivery"],
    "renewal": ["primary term", "option year", "notice window", "renewal notice", "renewal term"],
    "payment_terms": ["payment terms", "net terms", "early payment window", "early pay window"],
}

# Instruments that are cited but usually live outside the uploaded pack.
EXTERNAL = re.compile(r"\b(exhibit\s+[a-z0-9]+|schedule\s+\d+|annex\s+[a-z0-9]+|appendix\s+[a-z0-9]+|attachment\s+[a-z0-9]+)\b", re.I)
# "Section 8.2 of the Master Agreement" -> (8.2, "master agreement")
SECTION_OF = re.compile(r"\bsection\s+(\d+(?:\.\d+)*)\s+of\s+(?:the\s+)?([a-z][a-z \-]{2,40}?)(?=[,.;:)\n]|\s+(?:and|which|that|as)\b|$)", re.I)


class Document(TypedDict):
    index: int
    kind: str
    filename: str
    title: str


class ClauseInput(TypedDict):
    clause_id: str
    section: str
    heading: str
    text: str
    commercial: bool
    document_index: int


def _normalize(text: str) -> str:
    """Lower-case and turn separators into spaces so hyphenated phrases match."""
    return re.sub(r"\s+", " ", re.sub(r"[-_/]+", " ", text.lower()))


def _slug_alias(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return _normalize(re.sub(r"[-_]+", " ", stem)).strip()


def _label(document: Document) -> str:
    alias = _slug_alias(document["filename"])
    if alias:
        return alias[:1].upper() + alias[1:]
    return document["kind"].replace("_", " ").title()


def specific_aliases(document: Document) -> list[str]:
    """Names by which *this* document can be cited: filename stem and title."""
    aliases: list[str] = []
    stem = _slug_alias(document["filename"])
    if len(stem.split()) >= 2:
        aliases.append(stem)
    title = _normalize(document.get("title") or "")
    if title:
        phrase = " ".join(title.split()[:6]).strip(" .,:;")
        # A generic kind term on its own is not a specific name.
        generic = {term for terms in KIND_GENERICS.values() for term in terms}
        if len(phrase.split()) >= 2 and phrase not in aliases and phrase not in generic:
            aliases.append(phrase)
    return aliases


def _contains(haystack: str, needle: str) -> bool:
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _primary_by_kind(documents: list[Document]) -> dict[str, Document]:
    primary: dict[str, Document] = {}
    for document in sorted(documents, key=lambda item: item["index"]):
        primary.setdefault(document["kind"], document)
    return primary


def build_clause_network(documents: list[Document], clauses: list[ClauseInput]) -> dict[str, Any]:
    """Return {documents, clauses, references} for the spider-web view."""
    doc_by_index = {document["index"]: document for document in documents}
    aliases_by_doc = {document["index"]: specific_aliases(document) for document in documents}
    primary = _primary_by_kind(documents)
    clauses_by_id = {clause["clause_id"]: clause for clause in clauses}

    references: list[dict[str, Any]] = []
    external_nodes: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    out_count: dict[str, int] = {}
    in_count: dict[str, int] = {}

    def add(source_id: str, target_id: str, ref: dict[str, Any]) -> None:
        if (source_id, target_id) in seen:
            return
        seen.add((source_id, target_id))
        references.append({"id": f"ref:{len(references)}", "source": source_id, "target": target_id, **ref})
        out_count[source_id] = out_count.get(source_id, 0) + 1
        in_count[target_id] = in_count.get(target_id, 0) + 1

    for clause in clauses:
        source_index = clause["document_index"]
        source_kind = doc_by_index[source_index]["kind"] if source_index in doc_by_index else ""
        source_id = f"clause:{clause['clause_id']}"
        norm = _normalize(clause["text"])
        linked_kinds: set[str] = set()

        # 1. specific: another document named by title or filename.
        for document in documents:
            if document["index"] == source_index:
                continue
            for alias in aliases_by_doc[document["index"]]:
                if _contains(norm, alias):
                    add(source_id, f"doc:{document['index']}", {
                        "source_clause_id": clause["clause_id"],
                        "target_index": document["index"],
                        "target_clause_id": None,
                        "raw": alias,
                        "kind": "specific",
                        "resolved": True,
                    })
                    linked_kinds.add(document["kind"])
                    break

        # 2. section-of: "Section X of the Master Agreement" -> a precise clause.
        for section, instrument in SECTION_OF.findall(clause["text"]):
            target = _resolve_instrument(_normalize(instrument), documents, aliases_by_doc, primary, source_index)
            if target is None:
                continue
            target_clause_id = f"{target['index']}.{section}"
            if target_clause_id in clauses_by_id:
                add(source_id, f"clause:{target_clause_id}", {
                    "source_clause_id": clause["clause_id"],
                    "target_index": target["index"],
                    "target_clause_id": target_clause_id,
                    "raw": f"section {section} of {instrument.strip()}",
                    "kind": "specific",
                    "resolved": True,
                })
            else:
                add(source_id, f"doc:{target['index']}", {
                    "source_clause_id": clause["clause_id"],
                    "target_index": target["index"],
                    "target_clause_id": None,
                    "raw": f"section {section} of {instrument.strip()}",
                    "kind": "specific",
                    "resolved": True,
                })
            linked_kinds.add(target["kind"])

        # 3. generic: a curated kind term -> the primary document of that kind.
        for kind, terms in KIND_GENERICS.items():
            if kind in linked_kinds:
                continue
            # A document of kind K describing itself ("volume discount" inside a
            # discount schedule) is not a reference to a sibling of kind K. A real
            # sibling link names the sibling and is caught by the specific pass.
            if kind == source_kind:
                continue
            document = primary.get(kind)
            if document is None or document["index"] == source_index:
                continue
            hit = next((term for term in terms if _contains(norm, term)), None)
            if hit is None:
                continue
            add(source_id, f"doc:{document['index']}", {
                "source_clause_id": clause["clause_id"],
                "target_index": document["index"],
                "target_clause_id": None,
                "raw": hit,
                "kind": "generic",
                "resolved": True,
            })
            linked_kinds.add(kind)

        # 4. external: an instrument the pack does not contain.
        for match in EXTERNAL.finditer(clause["text"]):
            phrase = re.sub(r"\s+", " ", match.group(0).strip())
            slug = re.sub(r"[^a-z0-9]+", "-", phrase.lower()).strip("-")
            # Skip if the phrase actually names a document we already resolved.
            if _resolve_instrument(_normalize(phrase), documents, aliases_by_doc, primary, source_index):
                continue
            node_id = f"ext:{slug}"
            external_nodes[node_id] = {"id": node_id, "label": phrase.title()}
            add(source_id, node_id, {
                "source_clause_id": clause["clause_id"],
                "target_index": None,
                "target_clause_id": None,
                "raw": phrase,
                "kind": "external",
                "resolved": False,
            })

    return {
        "documents": [
            {
                "id": f"doc:{document['index']}",
                "index": document["index"],
                "kind": document["kind"],
                "label": _label(document),
                "filename": document["filename"],
                "title": document.get("title") or "",
                "clause_count": sum(1 for clause in clauses if clause["document_index"] == document["index"]),
            }
            for document in sorted(documents, key=lambda item: item["index"])
        ],
        "clauses": [
            {
                "id": f"clause:{clause['clause_id']}",
                "clause_id": clause["clause_id"],
                "section": clause["section"],
                "heading": clause["heading"],
                "text": clause["text"],
                "commercial": clause["commercial"],
                "document_index": clause["document_index"],
                "document_id": f"doc:{clause['document_index']}" if clause["document_index"] in doc_by_index else None,
                "outgoing": out_count.get(f"clause:{clause['clause_id']}", 0),
                "incoming": in_count.get(f"clause:{clause['clause_id']}", 0),
            }
            for clause in clauses
        ],
        "external": list(external_nodes.values()),
        "references": references,
    }


def cascade_targets(network: dict[str, Any], changed_clause_ids: Iterable[str]) -> dict[str, Any]:
    """Single-hop blast radius of an edit, read off the clause network.

    ``changed_clause_ids`` are bare ids (``"3.1"``) in the same
    ``{document_index}.{section}`` scheme the network and the compiled rules
    share. Returns the clauses in *other* documents that reference the edited
    clauses - the ones a change may strand - plus the reference edges that
    justify each hit. Only direct (one-hop) references are followed; a clause
    reached through a chain of two edges is not reported.
    """
    changed = {str(cid) for cid in changed_clause_ids}
    clause_by_id = {clause["clause_id"]: clause for clause in network.get("clauses", [])}
    # Documents that own a changed clause: a generic "the rebate schedule" style
    # link into such a document may depend on the edited clause too.
    changed_doc_indexes = {
        clause_by_id[cid]["document_index"] for cid in changed if cid in clause_by_id
    }

    impacted: set[str] = set()
    hits: list[dict[str, Any]] = []
    for ref in network.get("references", []):
        source = ref.get("source_clause_id")
        if source is None or source in changed:
            # The edited clause's own outgoing links are recompiled with it; we
            # only want the *dependents* that point back at what changed.
            continue
        precise = ref.get("target_clause_id") in changed
        doc_level = ref.get("target_clause_id") is None and ref.get("target_index") in changed_doc_indexes
        if precise or doc_level:
            impacted.add(source)
            hits.append(ref)
    return {
        "changed_clause_ids": sorted(changed),
        "impacted_clause_ids": sorted(impacted),
        "references": hits,
    }


def _resolve_instrument(
    instrument: str,
    documents: list[Document],
    aliases_by_doc: dict[int, list[str]],
    primary: dict[str, Document],
    source_index: int,
) -> Document | None:
    for document in documents:
        if document["index"] == source_index:
            continue
        for alias in aliases_by_doc[document["index"]]:
            if alias in instrument or instrument in alias:
                return document
    for kind, terms in KIND_GENERICS.items():
        if any(term in instrument for term in terms):
            document = primary.get(kind)
            if document is not None and document["index"] != source_index:
                return document
    return None
