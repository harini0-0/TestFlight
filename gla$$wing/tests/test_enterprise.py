from fastapi.testclient import TestClient
from gateway.main import app

client = TestClient(app)


def _headers() -> dict:
    token = client.post("/v1/auth/dev-token", json={"sub": "manager", "tenant_id": "demo", "role": "procurement_manager"})
    assert token.status_code == 200, token.text
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_meridian_loads_a_dense_engine_and_streams_a_rebate_leak():
    headers = _headers()
    loaded = client.post("/v1/demo/enterprise", headers=headers)
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    pack_id = body["pack_id"]
    pack = client.get(f"/v1/packs/{pack_id}", headers=headers)
    assert pack.status_code == 200, pack.text
    rules = pack.json()["bundle"]["rules"]
    types = {rule["rule_type"] for rule in rules}
    assert {"threshold_rebate", "price_match", "volume_discount", "payment_terms", "renewal_notice", "sla_penalty", "natural_language"} <= types
    assert sum(1 for rule in rules if rule["rule_type"] == "price_match") >= 12
    rebates = [rule for rule in rules if rule["rule_type"] == "threshold_rebate"]
    assert rebates
    assert all(rule["obligation"]["application"] == "rate_on_each_invoice_once_crossed" for rule in rebates)
    catalog = client.get("/v1/demo/enterprise/live", headers=headers)
    assert catalog.status_code == 200
    assert len(catalog.json()["files"]) == 7
    opening = client.post(f"/v1/packs/{pack_id}/live-next", headers=headers)
    assert opening.status_code == 200, opening.text
    assert opening.json()["transaction_id"] == "MER-10440"
    assert opening.json()["violations"] == []
    gap = client.post(f"/v1/packs/{pack_id}/live-next", headers=headers)
    assert gap.json()["transaction_id"] == "MER-10488"
    assert gap.json()["violations"]
    graph = client.get(f"/v1/contracts/{pack_id}/control-map", headers=headers)
    nodes = graph.json()["nodes"]
    assert len([node for node in nodes if node["column"] == "rule"]) >= 20
    assert any(node["kind"] == "finding" for node in nodes)
    again = client.post("/v1/demo/enterprise", headers=headers)
    assert again.json()["pack_id"] == pack_id
