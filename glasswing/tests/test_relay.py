import json
from pathlib import Path

from fastapi.testclient import TestClient
from gateway.main import app
from gateway.ratelimit import MemoryRateLimiter
from glasswing_adapters.db import OutboxRow, session_factory
from glasswing_adapters.relay import relay_unpublished
from glasswing_adapters.runtime import MemoryPublisher


def test_outbox_relay_publishes_each_event_once():
    Session, _engine = session_factory("sqlite://")
    session = Session()
    session.add(OutboxRow(event_id="evt-1", tenant_id="demo", event_type="TransactionAccepted", payload_json=json.dumps({"n": 1}), published=0))
    session.commit()
    publisher = MemoryPublisher()
    assert relay_unpublished(session, publisher) == 1
    session.commit()
    assert publisher.events == [("TransactionAccepted", {"n": 1}, "evt-1")]
    assert relay_unpublished(session, publisher) == 0


def test_memory_rate_limit_blocks_the_next_call():
    limiter = MemoryRateLimiter(limit=2, window=60)
    assert limiter.allow("tenant")
    assert limiter.allow("tenant")
    assert limiter.allow("tenant") is False


def test_sftp_drop_ingests_csv(tmp_path: Path, monkeypatch):
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "invoices.csv").write_text(
        "transaction_id,supplier_key,invoice_number,invoice_date,quantity,unit_price,description,category\n"
        "sftp-1,acme,SFTP-1,2026-01-15,1,10,Widget,goods\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GLASSWING_SFTP_ROOT", str(tmp_path))
    client = TestClient(app)
    token = client.post("/v1/auth/dev-token", json={"sub": "drop", "tenant_id": "demo", "role": "procurement_manager"})
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    response = client.post("/v1/connectors/sftp", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1
