import json
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from gateway.main import app

CONTRACT = Path("tests/golden/acme_contract.txt").read_text(encoding="utf-8")
client = TestClient(app)


def token(role: str, sub: str = "manager") -> dict:
    response = client.post("/v1/auth/dev-token", json={"sub": sub, "tenant_id": "demo", "role": role})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_compile_score_test_approve_and_recover_4200():
    headers = token("procurement_manager")
    uploaded = client.post(
        "/v1/contracts",
        content=CONTRACT.encode(),
        headers={**headers, "Idempotency-Key": "contract-1", "X-Filename": "acme.txt", "Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 200, uploaded.text
    document_id = uploaded.json()["document_id"]
    compiled = client.post(f"/v1/contracts/{document_id}/compile", headers=headers)
    assert compiled.status_code == 200, compiled.text
    rules = compiled.json()["rules"]
    rebate = next(rule for rule in rules if rule["rule_type"] == "threshold_rebate")
    assert rebate["source_clause_ids"] == ["8.2"]
    assert rebate["threshold"]["amount"] == "2000000"
    assert rebate["obligation"]["rate"] == "0.05"
    assert "application" in rebate["needs_confirmation"]
    assert rebate["value_band"] == "high"
    assert rebate["risk_band"] == "high"
    price = next(rule for rule in rules if rule["rule_type"] == "price_match")
    assert price["sku"] == "Widget A"
    assert price["contracted_price"]["amount"] == "10.0000"
    assert any(rule["rule_type"] == "natural_language" for rule in rules)
    assert all(rule["rule_type"] != "natural_language" or "Governing" not in json.dumps(rule) for rule in rules)

    blocked = client.post(
        f"/v1/bundles/{compiled.json()['bundle_id']}/approve",
        headers=headers,
        json={"human_switches": {}},
    )
    assert blocked.status_code == 409

    resolved = client.post(
        f"/v1/bundles/{compiled.json()['bundle_id']}/resolve",
        headers=headers,
        json={"rule_id": rebate["rule_id"], "field": "application", "value": "rate_on_each_invoice_once_crossed"},
    )
    assert resolved.status_code == 200, resolved.text
    rescored = next(rule for rule in resolved.json()["rules"] if rule["rule_id"] == rebate["rule_id"])
    assert rescored["needs_confirmation"] == []
    assert rescored["value_band"] == "high"
    assert rescored["risk_band"] == "low"

    report = client.post(f"/v1/bundles/{compiled.json()['bundle_id']}/tests", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["results"]
    assert all(row["passed"] for row in report.json()["results"] if row["author"] == "template")

    approved = client.post(
        f"/v1/bundles/{compiled.json()['bundle_id']}/approve",
        headers=headers,
        json={"human_switches": {rebate["rule_id"]: False}},
    )
    assert approved.status_code == 200, approved.text

    def post_invoice(number: str, amount: str, rebate_amount: str, key: str):
        quantity = str(Decimal(amount) / Decimal("10"))
        body = {
            "event_type": "invoice.posted",
            "transaction_id": number,
            "supplier_key": "acme",
            "invoice_number": number,
            "invoice_date": "2026-04-01",
            "lines": [
                {
                    "category": "goods",
                    "quantity": quantity,
                    "unit_price": {"amount": "10", "currency": "USD"},
                    "extended_amount": {"amount": amount, "currency": "USD"},
                    "rebate_amount": {"amount": rebate_amount, "currency": "USD"},
                    "sku": "Widget A",
                    "description": "Widget A",
                }
            ],
        }
        response = client.post("/v1/transactions", headers={**headers, "Idempotency-Key": key}, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    post_invoice("PRIOR", "2316000", "115800", "prior")
    leaked = post_invoice("INV-29381", "84000", "0", "leak")
    violation = next(item for item in leaked["evaluations"] if item["rule_id"] == rebate["rule_id"])
    assert violation["outcome"] == "violation"
    assert Decimal(violation["amount_at_risk"]["amount"]) == Decimal("4200.0000")
    price_eval = next(item for item in leaked["evaluations"] if item["rule_id"] == price["rule_id"])
    assert price_eval["outcome"] == "pass"
    assert price_eval["model_called"] is False

    findings = client.get("/v1/findings", headers=headers).json()["findings"]
    acme = next(item for item in findings if item["transaction_id"] == "INV-29381" and item["rule_id"] == rebate["rule_id"])
    assert acme["amount"] == "4200.0000"

    analyst = token("ap_analyst", "analyst")
    dispute = client.post(
        f"/v1/findings/{acme['finding_id']}/actions",
        headers=analyst,
        json={"action_type": "draft_supplier_dispute"},
    )
    assert dispute.status_code == 200, dispute.text
    assert "credit" in dispute.json()["draft_body"].lower()
    sent = client.post(f"/v1/actions/{dispute.json()['action_id']}/decide", headers=headers, json={"accept": True})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "succeeded"

    same = client.post(f"/v1/actions/{dispute.json()['action_id']}/decide", headers=headers, json={"accept": True})
    assert same.status_code == 409

    roi = client.get("/v1/roi", headers=headers).json()
    assert Decimal(roi["amount_at_risk"]) >= Decimal("4200")
    assert Decimal(roi["amount_recovered"]) >= Decimal("4200")

    control = client.get(f"/v1/contracts/{document_id}/control-map", headers=headers)
    assert control.status_code == 200
    assert any(node["kind"] == "threshold_rebate" for node in control.json()["nodes"])
    assert control.json()["replay"]

    edited = client.post(f"/v1/contracts/{document_id}/edit", headers=headers, json={})
    assert edited.status_code == 200, edited.text
    assert edited.json()["active"] is False
    live = client.get(f"/v1/contracts/{document_id}", headers=headers).json()
    assert live["bundle"]["active"] is True or live["bundle"]["version"] == 1 or edited.json()["version"] == 2

    audit = client.get("/v1/audit", headers=token("auditor", "auditor")).json()
    assert audit["events"]
    assert audit["events"][0]["prev_hash"] == "0" * 64


def test_connector_cannot_read_contracts():
    manager = token("org_admin", "admin")
    created = client.post(
        "/v1/admin/api-keys",
        headers=manager,
        json={"role": "connector", "scope": "ingest:write", "raw": "secret-key", "label": "erp"},
    )
    assert created.status_code == 200
    denied = client.get("/v1/contracts", headers={"X-Api-Key": "secret-key"})
    assert denied.status_code == 403


def test_body_tenant_is_rejected():
    headers = token("procurement_manager", "other")
    response = client.post(
        "/v1/transactions",
        headers={**headers, "Idempotency-Key": "nope"},
        json={
            "tenant_id": "other-tenant",
            "event_type": "invoice.posted",
            "transaction_id": "X",
            "supplier_key": "acme",
            "invoice_number": "X",
            "invoice_date": "2026-01-02",
            "lines": [{"extended_amount": {"amount": "1", "currency": "USD"}}],
        },
    )
    assert response.status_code == 403
