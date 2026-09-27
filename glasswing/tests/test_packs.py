from fastapi.testclient import TestClient
from gateway.main import app

client = TestClient(app)

CONTRACT = """Supplier: Northwind

8.2 Volume rebate
The buyer receives a 5% rebate on purchases exceeding $2,000,000.
"""

TERMS = """3. Settlement
2% 10 days net 30 when the invoice is paid early.
"""


def _headers() -> dict:
    token = client.post("/v1/auth/dev-token", json={"sub": "manager", "tenant_id": "demo", "role": "procurement_manager"})
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_documents_upload_without_a_category():
    headers = _headers()
    created = client.post("/v1/packs", json={"supplier_key": "Northwind"}, headers=headers)
    assert created.status_code == 200, created.text
    pack_id = created.json()["pack_id"]
    uploaded = client.post(
        f"/v1/packs/{pack_id}/files",
        content=CONTRACT.encode(),
        headers={**headers, "X-Filename": "notes.txt", "Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["kind"] == "document"
    detail = client.get(f"/v1/packs/{pack_id}", headers=headers)
    assert detail.json()["files"] == [{"document_id": uploaded.json()["document_id"], "kind": "document", "filename": "notes.txt"}]


def test_pack_joins_documents_into_one_engine():
    headers = _headers()
    created = client.post("/v1/packs", json={"supplier_key": "Northwind"}, headers=headers)
    assert created.status_code == 200, created.text
    pack_id = created.json()["pack_id"]
    for kind, name, body in (("contract", "master.txt", CONTRACT), ("payment_terms", "terms.txt", TERMS)):
        uploaded = client.post(
            f"/v1/packs/{pack_id}/files",
            content=body.encode(),
            headers={**headers, "X-Document-Kind": kind, "X-Filename": name, "Content-Type": "text/plain"},
        )
        assert uploaded.status_code == 200, uploaded.text
    processed = client.post(f"/v1/packs/{pack_id}/process", headers=headers)
    assert processed.status_code == 200, processed.text
    rules = processed.json()["rules"]
    assert any(rule["rule_type"] == "threshold_rebate" for rule in rules)
    assert any(rule["rule_type"] == "payment_terms" for rule in rules)
    assert processed.json()["tests"]["results"]
    detail = client.get(f"/v1/packs/{pack_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["files"]) == 2


def test_missing_expiry_can_be_cleared_before_approval():
    headers = _headers()
    created = client.post("/v1/packs", json={"supplier_key": "Northwind"}, headers=headers)
    pack_id = created.json()["pack_id"]
    body = "The contract expires unless notice is given 30 days before the end.\n"
    uploaded = client.post(
        f"/v1/packs/{pack_id}/files",
        content=body.encode(),
        headers={**headers, "X-Filename": "term.txt", "Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    processed = client.post(f"/v1/packs/{pack_id}/process", headers=headers)
    assert processed.status_code == 200, processed.text
    renewal = next(rule for rule in processed.json()["rules"] if rule["rule_type"] == "renewal_notice")
    assert "expiry" in renewal["needs_confirmation"]
    bundle_id = processed.json()["bundle_id"]
    blocked = client.post(f"/v1/bundles/{bundle_id}/approve", headers=headers, json={"human_switches": {}})
    assert blocked.status_code == 409
    cleared = client.post(
        f"/v1/bundles/{bundle_id}/resolve",
        headers=headers,
        json={"rule_id": renewal["rule_id"], "field": "expiry", "value": "none"},
    )
    assert cleared.status_code == 200, cleared.text
    updated = next(rule for rule in cleared.json()["rules"] if rule["rule_id"] == renewal["rule_id"])
    assert "expiry" not in updated["needs_confirmation"]
    assert updated["expiry"] is None
    approved = client.post(f"/v1/bundles/{bundle_id}/approve", headers=headers, json={"human_switches": {}})
    assert approved.status_code == 200, approved.text


def test_a_written_confirmation_is_saved_and_clears_the_field():
    headers = _headers()
    created = client.post("/v1/packs", json={"supplier_key": "Northwind"}, headers=headers)
    pack_id = created.json()["pack_id"]
    body = "DIR may terminate the Contract for convenience.\n"
    uploaded = client.post(
        f"/v1/packs/{pack_id}/files",
        content=body.encode(),
        headers={**headers, "X-Filename": "term.txt", "Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    processed = client.post(f"/v1/packs/{pack_id}/process", headers=headers)
    assert processed.status_code == 200, processed.text
    rule = next(item for item in processed.json()["rules"] if item["rule_type"] == "natural_language")
    bundle_id = processed.json()["bundle_id"]
    saved = client.post(
        f"/v1/bundles/{bundle_id}/resolve",
        headers=headers,
        json={"rule_id": rule["rule_id"], "field": "discount_rate", "value": "Adobe 6 percent, Microsoft 16.50 percent"},
    )
    assert saved.status_code == 200, saved.text
    updated = next(item for item in saved.json()["rules"] if item["rule_id"] == rule["rule_id"])
    assert updated["confirmations"]["discount_rate"] == "Adobe 6 percent, Microsoft 16.50 percent"
    assert "discount_rate" not in updated["needs_confirmation"]
    prose = "The minimum customer discount is 6.00% for Adobe and 16.50% for Microsoft."
    percent = client.post(
        f"/v1/bundles/{bundle_id}/resolve",
        headers=headers,
        json={"rule_id": rule["rule_id"], "field": "discount_percent", "value": prose},
    )
    assert percent.status_code == 200, percent.text
    updated = next(item for item in percent.json()["rules"] if item["rule_id"] == rule["rule_id"])
    assert updated["confirmations"]["discount_percent"] == prose
    assert updated["discount_percent"] is None
    assert "discount_percent" not in updated["needs_confirmation"]


def test_streamed_process_saves_the_engine():
    headers = _headers()
    created = client.post("/v1/packs", json={"supplier_key": "Northwind"}, headers=headers)
    pack_id = created.json()["pack_id"]
    uploaded = client.post(
        f"/v1/packs/{pack_id}/files",
        content=CONTRACT.encode(),
        headers={**headers, "X-Filename": "notes.txt", "Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    processed = client.post(
        f"/v1/packs/{pack_id}/process",
        headers={**headers, "Accept": "application/x-ndjson"},
    )
    assert processed.status_code == 200, processed.text
    events = [line for line in processed.text.splitlines() if line.strip()]
    assert events[-1].startswith('{"type": "result"')
    detail = client.get(f"/v1/packs/{pack_id}", headers=headers)
    assert detail.json()["bundle"]["rules"]
