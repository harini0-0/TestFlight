from compiler.references import build_clause_network, cascade_targets
from fastapi.testclient import TestClient
from gateway.main import app

client = TestClient(app)

DOCUMENTS = [
    {"index": 1, "kind": "contract", "filename": "master-agreement.txt", "title": "Master Supply Agreement"},
    {"index": 2, "kind": "contract", "filename": "price-schedule.txt", "title": "Price schedule effective 2026-01-01"},
    {"index": 3, "kind": "rebate", "filename": "annual-goods-rebate.txt", "title": "Annual goods rebate"},
    {"index": 4, "kind": "rebate", "filename": "growth-rebate.txt", "title": "Growth rebate"},
]

CLAUSES = [
    {"clause_id": "1.1", "section": "1", "heading": "Appointment", "commercial": True, "document_index": 1,
     "text": "This agreement covers goods only. Freight and tax are outside the rebate base."},
    {"clause_id": "1.4", "section": "4", "heading": "Price schedule", "commercial": True, "document_index": 1,
     "text": "Unit prices are stated in the attached price schedule. A shipment above the stated unit price is a leak."},
    {"clause_id": "2.1", "section": "1", "heading": "Prices", "commercial": True, "document_index": 2,
     "text": "Each line is the contracted unit price for goods. Freight and tax are excluded."},
    {"clause_id": "3.1", "section": "1", "heading": "Contract-year rebate", "commercial": True, "document_index": 3,
     "text": "The buyer receives a 3% rebate on eligible goods purchases exceeding $500,000."},
    {"clause_id": "4.1", "section": "1", "heading": "Growth rebate", "commercial": True, "document_index": 4,
     "text": "This schedule sits on top of the annual goods rebate and uses the same eligible base."},
]


def _edges(network: dict) -> set[tuple[str, str]]:
    return {(ref["source"], ref["target"]) for ref in network["references"]}


def test_specific_reference_by_filename_and_title():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    edges = _edges(network)
    # master §4 -> the price schedule document, by name.
    assert ("clause:1.4", "doc:2") in edges
    # growth rebate -> annual goods rebate, one schedule pointing at another.
    assert ("clause:4.1", "doc:3") in edges
    assert all(ref["kind"] == "specific" for ref in network["references"] if ref["source"] == "clause:4.1")


def test_generic_reference_by_kind_term():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    matches = [ref for ref in network["references"] if ref["source"] == "clause:1.1" and ref["target"] == "doc:3"]
    assert matches, "'rebate base' should link to the primary rebate document"
    assert matches[0]["kind"] == "generic"
    assert matches[0]["raw"] == "rebate base"


def test_no_intra_document_or_self_links():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    for ref in network["references"]:
        if ref["target"].startswith("doc:"):
            assert ref["target_index"] != CLAUSES[[c["clause_id"] for c in CLAUSES].index(ref["source_clause_id"])]["document_index"]


def test_section_of_resolves_to_a_precise_clause():
    documents = DOCUMENTS
    clauses = [
        {"clause_id": "3.1", "section": "1", "heading": "Rebate", "commercial": True, "document_index": 3,
         "text": "The buyer receives a 3% rebate."},
        {"clause_id": "1.9", "section": "9", "heading": "Liability", "commercial": True, "document_index": 1,
         "text": "Rebate accrual follows Section 1 of the annual goods rebate for the eligible base."},
    ]
    network = build_clause_network(documents, clauses)
    edges = _edges(network)
    assert ("clause:1.9", "clause:3.1") in edges


def test_external_instrument_becomes_a_marker():
    documents = [DOCUMENTS[0]]
    clauses = [
        {"clause_id": "1.1", "section": "1", "heading": "Pricing", "commercial": True, "document_index": 1,
         "text": "Pricing is set out in Exhibit A and delivered per Schedule 3."},
    ]
    network = build_clause_network(documents, clauses)
    external_ids = {node["id"] for node in network["external"]}
    assert "ext:exhibit-a" in external_ids
    assert "ext:schedule-3" in external_ids
    assert all(ref["resolved"] is False for ref in network["references"])


def test_cascade_finds_dependents_of_an_edited_clause():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    # Editing the annual goods rebate (doc 3): the growth rebate (4.1) sits on top
    # of it and the master clause 1.1 links to the rebate base -> both are stranded.
    cascade = cascade_targets(network, ["3.1"])
    assert "4.1" in cascade["impacted_clause_ids"]  # growth rebate -> doc 3
    assert "1.1" in cascade["impacted_clause_ids"]  # "rebate base" -> primary rebate doc
    # The edited clause's own outgoing links are not reported as stranded.
    assert "3.1" not in cascade["impacted_clause_ids"]
    assert cascade["changed_clause_ids"] == ["3.1"]


def test_cascade_follows_document_level_references():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    # Editing a price line (2.1) strands master clause 1.4, which points at the
    # price schedule *document* generically ("the attached price schedule").
    cascade = cascade_targets(network, ["2.1"])
    assert "1.4" in cascade["impacted_clause_ids"]


def test_cascade_is_empty_for_an_unknown_clause():
    network = build_clause_network(DOCUMENTS, CLAUSES)
    cascade = cascade_targets(network, ["9.9"])
    assert cascade["impacted_clause_ids"] == []


def _headers() -> dict:
    token = client.post("/v1/auth/dev-token", json={"sub": "manager", "tenant_id": "demo", "role": "procurement_manager"})
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_clause_network_endpoint_over_meridian_pack():
    headers = _headers()
    loaded = client.post("/v1/demo/enterprise", headers=headers)
    assert loaded.status_code == 200, loaded.text
    pack_id = loaded.json()["pack_id"]
    response = client.get(f"/v1/contracts/{pack_id}/clause-network", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["documents"]) >= 2
    assert body["clauses"]
    # The Meridian master agreement cites the attached price schedule.
    assert any(ref["kind"] in {"specific", "generic"} for ref in body["references"])
    # Cross-document only: no reference points inside its own document.
    index_by_clause = {clause["clause_id"]: clause["document_index"] for clause in body["clauses"]}
    for ref in body["references"]:
        if ref.get("target_index") is not None:
            assert ref["target_index"] != index_by_clause.get(ref["source_clause_id"])
