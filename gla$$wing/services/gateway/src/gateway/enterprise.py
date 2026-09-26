"""Load the Meridian Components sample pack and play its live stream one event at a time."""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from glasswing_adapters.db import DocumentRow, TransactionRow
from glasswing_domain.transactions import ClockTick, Invoice, PerformanceEvent, SpendEvent
from ingestion.connectors import invoices_from_csv
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from gateway.platform import Platform, PlatformError

EventAdapter = TypeAdapter(Invoice | SpendEvent | PerformanceEvent | ClockTick)
SUPPLIER = "meridian-components"
APPLICATION = "rate_on_each_invoice_once_crossed"


def samples_root() -> Path:
    override = os.environ.get("GLASSWING_SAMPLES", "").strip()
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "samples" / "meridian"
        if candidate.is_dir():
            return candidate
    raise PlatformError(500, "sample pack is not installed")


def manifest() -> dict:
    return json.loads((samples_root() / "manifest.json").read_text(encoding="utf-8"))


def live_catalog() -> list[dict]:
    root = samples_root()
    return [
        {"filename": (root / item["path"]).name, "summary": item["summary"]}
        for item in manifest()["live"]
    ]


def _events():
    root = samples_root()
    for item in manifest()["live"]:
        path = root / item["path"]
        summary = item["summary"]
        if path.suffix.lower() == ".csv":
            for invoice in invoices_from_csv(path.read_text(encoding="utf-8")):
                yield path.name, summary, invoice
        else:
            event = EventAdapter.validate_python(json.loads(path.read_text(encoding="utf-8")))
            yield path.name, summary, event


def load_enterprise(session: Session, tenant_id: str, actor: str) -> dict:
    platform = Platform(session)
    existing = session.scalars(
        select(DocumentRow).where(
            DocumentRow.tenant_id == tenant_id,
            DocumentRow.supplier_key == SUPPLIER,
            DocumentRow.kind == "pack",
        )
    ).first()
    if existing is not None and platform._active(tenant_id, existing.id) is not None:
        return {"pack_id": existing.id, "supplier_key": SUPPLIER, "live": live_catalog(), "status": "live"}
    data = manifest()
    if existing is None:
        existing = platform.create_pack(tenant_id, data["supplier_key"], date.fromisoformat(data["effective_date"]))
        root = samples_root()
        for item in data["documents"]:
            path = root / item["path"]
            platform.add_pack_file(
                tenant_id,
                existing.id,
                item["kind"],
                path.name,
                "text/plain",
                path.read_text(encoding="utf-8"),
                str(path),
            )
    bundle, _report = platform.process_pack(tenant_id, existing.id, actor)
    for rule in platform._rules(bundle):
        if "application" in rule.needs_confirmation:
            bundle = platform.resolve_field(tenant_id, bundle.id, rule.rule_id, "application", APPLICATION)
    platform.approve(tenant_id, bundle.id, actor, {}, {})
    return {"pack_id": existing.id, "supplier_key": SUPPLIER, "live": live_catalog(), "status": "approved"}


def play_next(session: Session, tenant_id: str, pack_id: str) -> dict:
    platform = Platform(session)
    pack = platform._pack(tenant_id, pack_id)
    if pack.supplier_key != SUPPLIER:
        raise PlatformError(409, "this stream belongs to the Meridian Components workspace")
    if platform._active(tenant_id, pack.id) is None:
        raise PlatformError(409, "approve the engine before playing the live stream")
    for filename, summary, event in _events():
        if session.get(TransactionRow, event.transaction_id):
            continue
        result = platform.accept_event(tenant_id, event, event.transaction_id)
        violations = []
        for evaluation in result.get("evaluations", []):
            if evaluation.get("outcome") != "violation":
                continue
            risk = evaluation.get("amount_at_risk") or {}
            violations.append(
                {
                    "rule_id": evaluation.get("rule_id"),
                    "explanation": evaluation.get("explanation", ""),
                    "amount": risk.get("amount") if isinstance(risk, dict) else None,
                }
            )
        return {
            "done": False,
            "filename": filename,
            "summary": summary,
            "transaction_id": event.transaction_id,
            "violations": violations,
        }
    return {
        "done": True,
        "filename": "",
        "summary": "The live stream has finished.",
        "transaction_id": "",
        "violations": [],
    }
