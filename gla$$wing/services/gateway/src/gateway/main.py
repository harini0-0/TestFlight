"""Public API. Internal services are called in-process here and as separate apps in Compose."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from glasswing_adapters.db import session_factory
from glasswing_adapters.relay import default_publisher, relay_unpublished
from glasswing_adapters.runtime import (
    LocalBlobStore,
    LocalPdfParser,
    S3BlobStore,
    configure_telemetry,
    langfuse_trace,
    looks_like_document,
)
from glasswing_domain.schema_export import export_schemas
from glasswing_domain.transactions import ClockTick, Invoice, PerformanceEvent, SpendEvent
from ingestion.connectors import invoices_from_csv
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from gateway.auth import Principal, decode_bearer, issue_dev_token, reject_client_tenant, require_role
from gateway.platform import Platform, PlatformError
from gateway.ratelimit import build_limiter

EventAdapter = TypeAdapter(Invoice | SpendEvent | PerformanceEvent | ClockTick)
MAX_BYTES = 20 * 1024 * 1024

configure_telemetry("glasswing-gateway")
Path("var").mkdir(exist_ok=True)
SessionLocal, _engine = session_factory(os.environ.get("DATABASE_URL", "sqlite:///var/glasswing.db"))
_bucket = os.environ.get("GLASSWING_S3_BUCKET", "").strip()
blobs = (
    S3BlobStore(_bucket, endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None)
    if _bucket
    else LocalBlobStore(Path(os.environ.get("GLASSWING_BLOB_ROOT", "var/blobs")))
)
limiter = build_limiter()

app = FastAPI(title="AI procurement control", version="0.1.0", openapi_version="3.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("GLASSWING_WEB_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    client = request.client.host if request.client else "unknown"
    key = request.headers.get("x-api-key") or request.headers.get("authorization") or client
    if not limiter.allow(key):
        return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
    return await call_next(request)


def db() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
        try:
            if relay_unpublished(session, default_publisher()):
                session.commit()
        except Exception:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def current_user(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    session: Session = Depends(db),
) -> Principal:
    platform = Platform(session)
    if x_api_key:
        row = platform.lookup_api_key(x_api_key)
        if row is None:
            raise HTTPException(status_code=401, detail="unknown api key")
        if row.role == "connector" and row.scope not in {"ingest:write", "read:findings"}:
            raise HTTPException(status_code=403, detail="api key scope rejected")
        return Principal(sub=row.label, tenant_id=row.tenant_id, role=row.role, scope=row.scope)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    return decode_bearer(authorization.removeprefix("Bearer ").strip())


def platform_for(session: Session = Depends(db), principal: Principal = Depends(current_user)) -> tuple[Platform, Principal]:
    return Platform(session), principal


def _guard(error: PlatformError) -> None:
    raise HTTPException(status_code=error.status, detail=error.detail)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/openapi/schemas")
def schemas() -> dict:
    return export_schemas()


@app.post("/v1/auth/dev-token")
def dev_token(body: dict) -> dict:
    if os.environ.get("GLASSWING_ENV") == "prod":
        raise HTTPException(status_code=404, detail="not found")
    try:
        token = issue_dev_token(body["sub"], body["tenant_id"], body["role"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"access_token": token, "token_type": "bearer"}


@app.post("/v1/contracts")
async def upload_contract(
    request: Request,
    principal: Principal = Depends(current_user),
    session: Session = Depends(db),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    require_role(principal, "procurement_manager")
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="contract exceeds 20MB")
    filename = request.headers.get("x-filename", "contract.txt")
    content_type = request.headers.get("content-type", "text/plain")
    if not looks_like_document(raw, filename):
        raise HTTPException(status_code=415, detail="unsupported document")
    text = raw.decode("utf-8")
    platform = Platform(session)
    reject_client_tenant(principal, {"tenant_id": request.headers.get("x-tenant-id")})
    document = platform.store_contract(
        principal.tenant_id,
        filename,
        content_type,
        text,
        blobs.put(principal.tenant_id, "pending", filename, raw),
        date.fromisoformat(request.headers.get("x-effective-date", "2026-01-01")),
    )
    document.storage_uri = blobs.put(principal.tenant_id, document.id, filename, raw)
    langfuse_trace("contract.ingest", document.sha256, "none", 0)
    return {"document_id": document.id, "supplier_key": document.supplier_key, "idempotency_key": idempotency_key}


@app.post("/v1/packs")
def create_pack(body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    reject_client_tenant(principal, body)
    supplier = str(body.get("supplier_key") or "").strip()
    if not supplier:
        raise HTTPException(status_code=400, detail="supplier_key is required")
    row = Platform(session).create_pack(principal.tenant_id, supplier, date.fromisoformat(str(body.get("effective_date") or "2026-01-01")))
    return {"pack_id": row.id, "supplier_key": row.supplier_key}


@app.get("/v1/packs")
def list_packs(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    from glasswing_adapters.db import DocumentRow
    from sqlalchemy import select

    rows = session.scalars(select(DocumentRow).where(DocumentRow.tenant_id == principal.tenant_id)).all()
    packs = [row for row in rows if row.pack_id in {"", row.id}]
    return {
        "packs": [
            {"pack_id": row.id, "supplier_key": row.supplier_key, "filename": row.filename, "status": row.status, "kind": row.kind}
            for row in packs
        ]
    }


@app.get("/v1/packs/{pack_id}")
def get_pack(pack_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    platform = Platform(session)
    try:
        pack = platform._pack(principal.tenant_id, pack_id)
        bundle = platform._latest(principal.tenant_id, pack.id)
        files = platform._pack_files(principal.tenant_id, pack.id)
    except PlatformError as exc:
        _guard(exc)
    return {
        "pack_id": pack.id,
        "supplier_key": pack.supplier_key,
        "status": pack.status,
        "kind": pack.kind,
        "files": [{"document_id": row.id, "kind": row.kind, "filename": row.filename} for row in files],
        "bundle": None
        if bundle is None
        else {
            "bundle_id": bundle.id,
            "version": bundle.version,
            "status": bundle.status,
            "active": bool(bundle.active),
            "rules": [rule.model_dump(mode="json") for rule in platform._rules(bundle)],
            "clauses": [clause.model_dump(mode="json") for clause in platform._clauses(bundle)],
            "test_run_id": bundle.test_run_id,
        },
    }


@app.post("/v1/packs/{pack_id}/files")
async def upload_pack_file(
    pack_id: str,
    request: Request,
    principal: Principal = Depends(current_user),
    session: Session = Depends(db),
) -> dict:
    require_role(principal, "procurement_manager")
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="document exceeds 20MB")
    filename = request.headers.get("x-filename", "document.txt")
    kind = request.headers.get("x-document-kind", "contract")
    if not looks_like_document(raw, filename):
        raise HTTPException(status_code=415, detail="unsupported document")
    text = LocalPdfParser().extract_text(raw, filename).strip()
    if not text:
        raise HTTPException(status_code=422, detail="no text could be read from the document")
    platform = Platform(session)
    try:
        row = platform.add_pack_file(
            principal.tenant_id,
            pack_id,
            kind,
            filename,
            request.headers.get("content-type", "text/plain"),
            text,
            blobs.put(principal.tenant_id, "pending", filename, raw),
        )
    except PlatformError as exc:
        _guard(exc)
    row.storage_uri = blobs.put(principal.tenant_id, row.id, filename, raw)
    return {"document_id": row.id, "kind": row.kind, "filename": row.filename}


@app.post("/v1/packs/{pack_id}/process")
def process_pack(pack_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    platform = Platform(session)
    try:
        bundle, report = platform.process_pack(principal.tenant_id, pack_id, principal.sub)
    except PlatformError as exc:
        _guard(exc)
    return {
        "bundle_id": bundle.id,
        "version": bundle.version,
        "status": bundle.status,
        "active": bool(bundle.active),
        "rules": [rule.model_dump(mode="json") for rule in platform._rules(bundle)],
        "tests": report,
    }


@app.post("/v1/contracts/{document_id}/rule-edit")
def rule_edit(document_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    reject_client_tenant(principal, body)
    platform = Platform(session)
    try:
        bundle, live_kept = platform.edit_rule_field(
            principal.tenant_id,
            document_id,
            body["rule_id"],
            body["field"],
            str(body["value"]),
            principal.sub,
        )
    except PlatformError as exc:
        _guard(exc)
    return {
        "bundle_id": bundle.id,
        "version": bundle.version,
        "status": bundle.status,
        "active": bool(bundle.active),
        "live_kept": live_kept,
    }


@app.get("/v1/contracts")
def list_contracts(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    from glasswing_adapters.db import DocumentRow
    from sqlalchemy import select

    rows = session.scalars(select(DocumentRow).where(DocumentRow.tenant_id == principal.tenant_id)).all()
    return {
        "contracts": [
            {"document_id": row.id, "supplier_key": row.supplier_key, "filename": row.filename, "status": row.status}
            for row in rows
        ]
    }


@app.get("/v1/contracts/{document_id}")
def get_contract(document_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    platform = Platform(session)
    try:
        document = platform._document(principal.tenant_id, document_id)
        bundle = platform._latest(principal.tenant_id, document_id)
    except PlatformError as exc:
        _guard(exc)
    return {
        "document_id": document.id,
        "supplier_key": document.supplier_key,
        "text": document.body,
        "bundle": None
        if bundle is None
        else {
            "bundle_id": bundle.id,
            "version": bundle.version,
            "status": bundle.status,
            "active": bool(bundle.active),
            "rules": platform._rules(bundle) and [rule.model_dump(mode="json") for rule in platform._rules(bundle)],
            "clauses": [clause.model_dump(mode="json") for clause in platform._clauses(bundle)],
            "test_run_id": bundle.test_run_id,
        },
    }


@app.post("/v1/contracts/{document_id}/compile")
def compile_contract(document_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    platform = Platform(session)
    try:
        bundle = platform.compile(principal.tenant_id, document_id, principal.sub)
    except PlatformError as exc:
        _guard(exc)
    langfuse_trace("compiler", bundle.prompt_hash, bundle.model_id, 1)
    return {"bundle_id": bundle.id, "version": bundle.version, "rules": [rule.model_dump(mode="json") for rule in platform._rules(bundle)]}


@app.post("/v1/bundles/{bundle_id}/resolve")
def resolve(bundle_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    reject_client_tenant(principal, body)
    platform = Platform(session)
    try:
        bundle = platform.resolve_field(principal.tenant_id, bundle_id, body["rule_id"], body["field"], body["value"])
    except PlatformError as exc:
        _guard(exc)
    return {"bundle_id": bundle.id, "rules": [rule.model_dump(mode="json") for rule in platform._rules(bundle)]}


@app.post("/v1/bundles/{bundle_id}/tests")
def run_tests(bundle_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "auditor")
    platform = Platform(session)
    try:
        return platform.run_tests(principal.tenant_id, bundle_id)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.post("/v1/bundles/{bundle_id}/approve")
def approve(bundle_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    reject_client_tenant(principal, body)
    platform = Platform(session)
    try:
        bundle = platform.approve(
            principal.tenant_id,
            bundle_id,
            principal.sub,
            body.get("human_switches") or {},
            body.get("waived") or {},
        )
    except PlatformError as exc:
        _guard(exc)
    return {"bundle_id": bundle.id, "version": bundle.version, "status": bundle.status}


@app.post("/v1/contracts/{document_id}/edit")
def edit_contract(document_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    reject_client_tenant(principal, body)
    platform = Platform(session)
    try:
        bundle = platform.edit_contract(principal.tenant_id, document_id, body.get("text"), principal.sub)
    except PlatformError as exc:
        _guard(exc)
    return {"bundle_id": bundle.id, "version": bundle.version, "status": bundle.status, "active": bool(bundle.active)}


@app.post("/v1/bundles/{bundle_id}/human-switch")
def human_switch(bundle_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    platform = Platform(session)
    try:
        rule = platform.set_human_switch(principal.tenant_id, bundle_id, body["rule_id"], bool(body["required"]), principal.sub)
    except PlatformError as exc:
        _guard(exc)
    return rule.model_dump(mode="json")


@app.get("/v1/contracts/{document_id}/control-map")
def control_map(document_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    platform = Platform(session)
    try:
        return platform.control_map(principal.tenant_id, document_id)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.get("/v1/contracts/{document_id}/replay-diff")
def replay_diff(document_id: str, bundle_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "auditor")
    platform = Platform(session)
    try:
        return platform.replay_diff(principal.tenant_id, bundle_id)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.get("/v1/portfolio/graph")
def portfolio(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    return Platform(session).portfolio(principal.tenant_id)


@app.post("/v1/transactions")
def post_transaction(
    body: dict,
    principal: Principal = Depends(current_user),
    session: Session = Depends(db),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    require_role(principal, "connector", "procurement_manager", "ap_analyst")
    if principal.role == "connector" and principal.scope not in {"", "ingest:write"}:
        raise HTTPException(status_code=403, detail="connector key cannot ingest")
    reject_client_tenant(principal, body)
    platform = Platform(session)
    event = EventAdapter.validate_python(body)
    try:
        return platform.accept_event(principal.tenant_id, event, idempotency_key)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.post("/v1/connectors/webhook")
def webhook(
    body: dict,
    principal: Principal = Depends(current_user),
    session: Session = Depends(db),
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> dict:
    return post_transaction(body, principal, session, idempotency_key)


@app.post("/v1/connectors/csv")
def csv_drop(
    body: dict,
    principal: Principal = Depends(current_user),
    session: Session = Depends(db),
) -> dict:
    require_role(principal, "connector", "procurement_manager")
    invoices = invoices_from_csv(body["csv"])
    platform = Platform(session)
    results = []
    for invoice in invoices:
        results.append(platform.accept_event(principal.tenant_id, invoice, f"csv-{invoice.transaction_id}"))
    return {"accepted": len(results), "results": results}


@app.post("/v1/connectors/sftp")
def sftp_drop(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    """Pull CSV invoices from the tenant SFTP drop directory."""
    require_role(principal, "connector", "procurement_manager")
    from ingestion.connectors import invoices_from_directory

    root = Path(os.environ.get("GLASSWING_SFTP_ROOT", "var/sftp")) / principal.tenant_id
    if not root.is_dir():
        return {"accepted": 0, "results": []}
    platform = Platform(session)
    results = []
    for invoice in invoices_from_directory(root):
        results.append(platform.accept_event(principal.tenant_id, invoice, f"sftp-{invoice.transaction_id}"))
    return {"accepted": len(results), "results": results}


@app.get("/v1/findings")
def list_findings(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    if principal.role == "connector":
        raise HTTPException(status_code=403, detail="connector credentials cannot read findings")
    from glasswing_adapters.db import FindingRow
    from sqlalchemy import select

    rows = session.scalars(select(FindingRow).where(FindingRow.tenant_id == principal.tenant_id)).all()
    return {
        "findings": [
            {
                "finding_id": row.id,
                "rule_id": row.rule_id,
                "transaction_id": row.transaction_id,
                "status": row.status,
                "amount": row.amount,
                "currency": row.currency,
                "document_id": row.document_id,
                "bundle_id": row.bundle_id,
            }
            for row in rows
        ]
    }


@app.get("/v1/findings/{finding_id}")
def get_finding(finding_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    platform = Platform(session)
    try:
        row = platform._finding(principal.tenant_id, finding_id)
    except PlatformError as exc:
        _guard(exc)
    import json

    return {"finding_id": row.id, "status": row.status, "amount": row.amount, "currency": row.currency, **json.loads(row.payload_json)}


@app.post("/v1/findings/{finding_id}/confirm")
def confirm_finding(finding_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst")
    platform = Platform(session)
    try:
        row = platform.confirm_finding(principal.tenant_id, finding_id, principal.sub, bool(body.get("accept", True)))
    except PlatformError as exc:
        _guard(exc)
    return {"finding_id": row.id, "status": row.status}


@app.post("/v1/findings/{finding_id}/investigate")
def investigate(finding_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst")
    platform = Platform(session)
    try:
        return platform.investigate(principal.tenant_id, finding_id)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.post("/v1/findings/{finding_id}/actions")
def propose_action(finding_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst")
    platform = Platform(session)
    try:
        return platform.propose(principal.tenant_id, finding_id, body["action_type"], principal.sub)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.post("/v1/actions/{action_id}/decide")
def decide_action(action_id: str, body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager")
    platform = Platform(session)
    try:
        return platform.decide_action(principal.tenant_id, action_id, principal.sub, bool(body.get("accept", True)))
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.get("/v1/roi")
def roi(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "procurement_manager", "ap_analyst", "auditor")
    return Platform(session).roi(principal.tenant_id)


@app.get("/v1/audit")
def audit(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "auditor", "procurement_manager", "org_admin")
    return {"events": Platform(session).audit_entries(principal.tenant_id)}


@app.get("/v1/admin/settings")
def get_settings(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "org_admin", "procurement_manager")
    row = Platform(session).settings(principal.tenant_id)
    return {
        "high_value_threshold": row.high_value_threshold,
        "review_minutes": row.review_minutes,
        "sod_required": bool(row.sod_required),
        "connector_write": bool(row.connector_write),
    }


@app.put("/v1/admin/settings")
def put_settings(body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "org_admin", "procurement_manager")
    reject_client_tenant(principal, body)
    row = Platform(session).update_settings(principal.tenant_id, str(body["high_value_threshold"]), str(body.get("review_minutes", "6")))
    if "connector_write" in body:
        row.connector_write = 1 if body["connector_write"] else 0
    if "sod_required" in body:
        row.sod_required = 1 if body["sod_required"] else 0
    return {"high_value_threshold": row.high_value_threshold, "connector_write": bool(row.connector_write)}


@app.post("/v1/admin/api-keys")
def create_key(body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "org_admin")
    Platform(session).create_api_key(principal.tenant_id, body["role"], body["scope"], body["raw"], body.get("label", "connector"))
    return {"status": "stored"}


@app.post("/v1/admin/retention")
def retention(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    require_role(principal, "org_admin")
    Platform(session).retention_delete(principal.tenant_id, principal.sub)
    return {"deleted": principal.tenant_id}


@app.post("/v1/demo/seed")
def demo_seed(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    if os.environ.get("GLASSWING_ENV") == "prod":
        raise HTTPException(status_code=404, detail="not found")
    require_role(principal, "procurement_manager", "org_admin")
    from gateway.seed import seed_tenant

    return seed_tenant(session, principal.tenant_id)


@app.post("/v1/demo/enterprise")
def demo_enterprise(principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    if os.environ.get("GLASSWING_ENV") == "prod":
        raise HTTPException(status_code=404, detail="not found")
    require_role(principal, "procurement_manager", "org_admin")
    from gateway.enterprise import load_enterprise

    try:
        return load_enterprise(session, principal.tenant_id, principal.sub)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.get("/v1/demo/enterprise/live")
def demo_enterprise_live(principal: Principal = Depends(current_user)) -> dict:
    if os.environ.get("GLASSWING_ENV") == "prod":
        raise HTTPException(status_code=404, detail="not found")
    require_role(principal, "procurement_manager", "org_admin", "ap_analyst", "auditor")
    from gateway.enterprise import live_catalog

    return {"files": live_catalog()}


@app.post("/v1/packs/{pack_id}/live-next")
def live_next(pack_id: str, principal: Principal = Depends(current_user), session: Session = Depends(db)) -> dict:
    if os.environ.get("GLASSWING_ENV") == "prod":
        raise HTTPException(status_code=404, detail="not found")
    require_role(principal, "procurement_manager", "org_admin")
    from gateway.enterprise import play_next

    try:
        return play_next(session, principal.tenant_id, pack_id)
    except PlatformError as exc:
        _guard(exc)
        return {}


@app.post("/v1/clock")
def clock(body: dict, principal: Principal = Depends(current_user), session: Session = Depends(db), idempotency_key: str = Header(alias="Idempotency-Key")) -> dict:
    require_role(principal, "procurement_manager", "org_admin")
    tick = ClockTick(
        transaction_id=body["transaction_id"],
        supplier_key=body["supplier_key"],
        as_of=date.fromisoformat(body["as_of"]),
        notice_recorded=bool(body.get("notice_recorded", False)),
    )
    try:
        return Platform(session).accept_event(principal.tenant_id, tick, idempotency_key)
    except PlatformError as exc:
        _guard(exc)
        return {}
