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
