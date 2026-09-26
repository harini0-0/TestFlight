"""SQLAlchemy models. Postgres uses schemas via infra/sql; SQLite uses the same table names."""

from __future__ import annotations

import os

from sqlalchemy import String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "ingestion_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_key: Mapped[str] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32), default="contract")
    pack_id: Mapped[str] = mapped_column(String(64), default="")


class BundleRow(Base):
    __tablename__ = "control_bundles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    active: Mapped[int] = mapped_column(default=0)
    supplier_key: Mapped[str] = mapped_column(String(128))
    document_hash: Mapped[str] = mapped_column(String(64))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(128))
    test_run_id: Mapped[str] = mapped_column(String(64), default="")
    rules_json: Mapped[str] = mapped_column(Text)
    clauses_json: Mapped[str] = mapped_column(Text)
    embeddings_json: Mapped[str] = mapped_column(Text, default="[]")


class TransactionRow(Base):
    __tablename__ = "ingestion_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_key: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(128), default="")


class LedgerRow(Base):
    __tablename__ = "control_ledger"

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    supplier_key: Mapped[str] = mapped_column(String(128))
    document_id: Mapped[str] = mapped_column(String(64))
    rule_id: Mapped[str] = mapped_column(String(64))
    period_key: Mapped[str] = mapped_column(String(64))
    metric: Mapped[str] = mapped_column(String(64))
    balance: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8))
    applied_json: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(default=0)


class EvaluationRow(Base):
    __tablename__ = "control_evaluations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    bundle_id: Mapped[str] = mapped_column(String(64))
    transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(default=0)


class FindingRow(Base):
    __tablename__ = "control_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    bundle_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    rule_id: Mapped[str] = mapped_column(String(64))
    transaction_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    amount: Mapped[str] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(8))
    estimated: Mapped[int] = mapped_column(default=0)
    booked: Mapped[int] = mapped_column(default=1)
    payload_json: Mapped[str] = mapped_column(Text)


class ActionRow(Base):
    __tablename__ = "actions_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


class AuditRowModel(Base):
    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    row_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class OutboxRow(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    published: Mapped[int] = mapped_column(default=0)


class ApiKeyRow(Base):
    __tablename__ = "gateway_api_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(128))


class IdempotencyRow(Base):
    __tablename__ = "gateway_idempotency"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text)


class SettingRow(Base):
    __tablename__ = "gateway_settings"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    high_value_threshold: Mapped[str] = mapped_column(String(64))
    review_minutes: Mapped[str] = mapped_column(String(16), default="6")
    sod_required: Mapped[int] = mapped_column(default=1)
    connector_write: Mapped[int] = mapped_column(default=0)


class InvestigationRow(Base):
    __tablename__ = "investigator_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    finding_id: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


def make_engine(url: str | None = None):
    database_url = url or os.environ.get("DATABASE_URL") or "sqlite://"
    if database_url == "sqlite://" or database_url.startswith("sqlite"):
        return create_engine(database_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(database_url)


def session_factory(url: str | None = None):
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    _ensure_document_columns(engine)
    return sessionmaker(bind=engine, expire_on_commit=False), engine


def _ensure_document_columns(engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(ingestion_documents)").fetchall()
        names = {row[1] for row in rows}
        if "kind" not in names:
            conn.exec_driver_sql("ALTER TABLE ingestion_documents ADD COLUMN kind VARCHAR(32) DEFAULT 'contract'")
        if "pack_id" not in names:
            conn.exec_driver_sql("ALTER TABLE ingestion_documents ADD COLUMN pack_id VARCHAR(64) DEFAULT ''")


def tenant_clause(session: Session, model, tenant_id: str):
    return session.query(model).filter(model.tenant_id == tenant_id)
