"""Composition root. Services keep their own tables and talk through this API plus the outbox."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

from actions.machine import Action
from actions.machine import approve as approve_action
from actions.machine import execute as execute_action
from actions.machine import propose as propose_action
from audit.chain import AuditLog
from compiler.llm_compile import CompilerFailure, LlmCompiler
from compiler.pipeline import compiler_prompt_hash, score_rule
from compiler.recording_model import RecordingModel
from compiler.references import build_clause_network, cascade_targets
from compiler.testgen import template_cases
from control_engine.ledger import ZERO, evaluate_condition, natural_language_applicable
from control_engine.sandbox import run_suite
from glasswing_adapters.db import (
    ActionRow,
    ApiKeyRow,
    AuditRowModel,
    BundleRow,
    DocumentRow,
    EvaluationRow,
    FindingRow,
    IdempotencyRow,
    InvestigationRow,
    LedgerRow,
    OutboxRow,
    SettingRow,
    TransactionRow,
)
from glasswing_adapters.llm import LlmError, chat_client_from_env, llm_enabled
from glasswing_adapters.runtime import hash_api_key
from glasswing_domain.events import AuditEvent
from glasswing_domain.ids import uuid7
from glasswing_domain.money import Money
from glasswing_domain.ontology import Clause
from glasswing_domain.periods import period_key
from glasswing_domain.rules import RuleIR, engine_triggers
from glasswing_domain.transactions import ClockTick, Invoice, PerformanceEvent, SpendEvent
from ingestion.normalize import NormalizeFailure, normalize_unstructured
from investigator.service import investigate_exception, judge_natural_language, search_clauses
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

from compiler import compile_document, document_hash

Event = Invoice | SpendEvent | PerformanceEvent | ClockTick
_events: TypeAdapter[Event] = TypeAdapter(Event)
PACK_KINDS = ("contract", "rebate", "discount", "sla", "renewal", "payment_terms", "document")
KIND_LABELS = {
    "contract": "Supplier contract",
    "rebate": "Rebate schedule",
    "discount": "Discount schedule",
    "sla": "Service levels",
    "renewal": "Renewal dates",
    "payment_terms": "Payment terms",
}
_HEADING_LINE = re.compile(r"(?m)^(?P<section>\d+(?:\.\d+)*)(?P<dot>\.?)(?P<space>\s+)")

SONNET = "anthropic.claude-sonnet"
HAIKU = "anthropic.claude-haiku"


class PlatformError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class ModelBridge:
    def __init__(self, model: RecordingModel) -> None:
        self.model = model

    def complete(self, *, model_id: str, system: str, user: str, schema_name: str) -> str:
        if schema_name == "NlJudgment":
            return self.model.judge(system, user)
        if schema_name == "Investigation":
            return self.model.investigate(system, user)
        if schema_name == "AgentCases":
            return "[]"
        return "{}"


class Platform:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._audit_cache: dict[str, AuditLog] = {}

    def settings(self, tenant_id: str) -> SettingRow:
        row = self.session.get(SettingRow, tenant_id)
        if row is None:
            row = SettingRow(
                tenant_id=tenant_id,
                high_value_threshold="100000",
                review_minutes="6",
                sod_required=1,
                connector_write=0,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def update_settings(self, tenant_id: str, high_value_threshold: str, review_minutes: str) -> SettingRow:
        row = self.settings(tenant_id)
        row.high_value_threshold = high_value_threshold
        row.review_minutes = review_minutes
        self._audit(tenant_id, "system", "settings.update", [tenant_id], {"high_value_threshold": high_value_threshold})
        return row

    def create_api_key(self, tenant_id: str, role: str, scope: str, raw: str, label: str) -> None:
        self.session.add(
            ApiKeyRow(key_hash=hash_api_key(raw), tenant_id=tenant_id, role=role, scope=scope, label=label)
        )

    def lookup_api_key(self, raw: str) -> ApiKeyRow | None:
        return self.session.get(ApiKeyRow, hash_api_key(raw))

    def store_contract(
        self,
        tenant_id: str,
        filename: str,
        content_type: str,
        text: str,
        storage_uri: str,
        effective_date: date,
        supplier_key: str | None = None,
    ) -> DocumentRow:
        supplier = supplier_key or _supplier_from_text(text)
        document_id = uuid7()
        row = DocumentRow(
            id=document_id,
            tenant_id=tenant_id,
            supplier_key=supplier,
            filename=filename,
            content_type=content_type,
            sha256=document_hash(text),
            storage_uri=storage_uri,
            body=text,
            effective_date=effective_date.isoformat(),
            status="stored",
            kind="contract",
            pack_id=document_id,
        )
        self.session.add(row)
        self._outbox(tenant_id, "ContractDocumentStored", {"document_id": document_id})
        self._audit(tenant_id, "system", "contract.stored", [document_id], {"filename": filename})
        return row

    def create_pack(self, tenant_id: str, supplier_key: str, effective_date: date) -> DocumentRow:
        document_id = uuid7()
        row = DocumentRow(
            id=document_id,
            tenant_id=tenant_id,
            supplier_key=supplier_key.strip().lower().replace(" ", "-") or "supplier",
            filename=f"{supplier_key}.txt",
            content_type="text/plain",
            sha256=document_hash(""),
            storage_uri="",
            body="",
            effective_date=effective_date.isoformat(),
            status="stored",
            kind="pack",
            pack_id=document_id,
        )
        self.session.add(row)
        self._audit(tenant_id, "system", "pack.created", [document_id], {"supplier_key": row.supplier_key})
        return row

    def add_pack_file(
        self,
        tenant_id: str,
        pack_id: str,
        kind: str,
        filename: str,
        content_type: str,
        text: str,
        storage_uri: str,
    ) -> DocumentRow:
        if kind not in PACK_KINDS:
            raise PlatformError(400, "unknown document kind")
        pack = self._pack(tenant_id, pack_id)
        document_id = uuid7()
        row = DocumentRow(
            id=document_id,
            tenant_id=tenant_id,
            supplier_key=pack.supplier_key,
            filename=filename,
            content_type=content_type,
            sha256=document_hash(text),
            storage_uri=storage_uri,
            body=text,
            effective_date=pack.effective_date,
            status="stored",
            kind=kind,
            pack_id=pack.id,
        )
        self.session.add(row)
        self._outbox(tenant_id, "ContractDocumentStored", {"document_id": document_id, "pack_id": pack.id, "kind": kind})
        self._audit(tenant_id, "system", "pack.file_stored", [document_id], {"filename": filename, "kind": kind})
        return row

    def process_pack(self, tenant_id: str, pack_id: str, actor: str, on_progress=None) -> tuple[BundleRow, dict]:
        pack = self._pack(tenant_id, pack_id)
        bundle = self._recompile_pack(tenant_id, pack, actor, on_progress=on_progress)
        if on_progress:
            on_progress({"index": 1, "total": 1, "detail": "Running practice checks on the rules just read."})
        report = self.run_tests(tenant_id, bundle.id)
        return bundle, report

    def _recompile_pack(self, tenant_id: str, pack: DocumentRow, actor: str, on_progress=None) -> BundleRow:
        """Rebuild the pack's flattened body from its sources and compile a draft."""
        sources = self._pack_sources(pack)
        if not sources:
            raise PlatformError(409, "upload at least one document")
        if on_progress:
            on_progress({"index": 0, "total": 0, "detail": f"Preparing {len(sources)} uploaded file{'s' if len(sources) != 1 else ''}."})
        parts: list[str] = []
        for index, (kind, filename, body) in enumerate(sources, start=1):
            parts.append(_prepare_source(index, _source_heading(kind, filename), body))
        combined = "\n\n".join(parts)
        pack.body = combined
        pack.sha256 = document_hash(combined)
        pack.status = "stored"
        return self.compile(tenant_id, pack.id, actor, on_progress=on_progress)

    def edit_rule_field(self, tenant_id: str, document_id: str, rule_id: str, field: str, value: str, actor: str) -> tuple[BundleRow, bool]:
        bundle = self._latest(tenant_id, document_id)
        if bundle is None:
            raise PlatformError(404, "no bundle")
        live = self._active(tenant_id, document_id)
        if bundle.status != "draft":
            bundle = self.edit_contract(tenant_id, document_id, None, actor)
        updated = self.resolve_field(tenant_id, bundle.id, rule_id, field, value)
        return updated, live is not None and live.id != updated.id

    def compile(self, tenant_id: str, document_id: str, actor: str, on_progress=None) -> BundleRow:
        document = self._document(tenant_id, document_id)
        model = self._model_for_compile(document.supplier_key)
        threshold = Decimal(self.settings(tenant_id).high_value_threshold)
        try:
            clauses, rules, embeddings = compile_document(
                document.body, document.supplier_key, threshold, model, on_progress=on_progress
            )
        except CompilerFailure as exc:
            document.status = "compiler_failed"
            self._audit(tenant_id, actor, "bundle.compile_failed", [document_id], {"detail": exc.detail})
            raise PlatformError(422, exc.detail) from exc
        version = self._next_version(tenant_id, document_id)
        bundle = BundleRow(
            id=uuid7(),
            tenant_id=tenant_id,
            document_id=document_id,
            version=version,
            status="draft",
            active=0,
            supplier_key=document.supplier_key,
            document_hash=document.sha256,
            prompt_hash=compiler_prompt_hash(),
            model_id=model.model_id,
            test_run_id="",
            rules_json=_dump([rule.model_dump(mode="json") for rule in rules]),
            clauses_json=_dump([clause.model_dump(mode="json") for clause in clauses]),
            embeddings_json=_dump(embeddings),
        )
        self.session.add(bundle)
        document.status = "compiled"
        self._audit(tenant_id, actor, "bundle.compiled", [bundle.id], {"version": version, "rules": len(rules)})
        return bundle

    def resolve_field(self, tenant_id: str, bundle_id: str, rule_id: str, field: str, value: str) -> BundleRow:
        bundle = self._bundle(tenant_id, bundle_id)
        if bundle.status != "draft":
            raise PlatformError(409, "only a draft can be edited before approval")
        rules = self._rules(bundle)
        clauses = {clause.clause_id: clause for clause in self._clauses(bundle)}
        updated: list[RuleIR] = []
        for rule in rules:
            if rule.rule_id != rule_id:
                updated.append(rule)
                continue
            data = rule.model_dump()
            if field == "application":
                if data.get("obligation") is None:
                    data["obligation"] = {"rate": "0", "application": value}
                else:
                    data["obligation"]["application"] = value
                data["needs_confirmation"] = [item for item in data["needs_confirmation"] if item != "application"]
            elif field == "rate":
                if data.get("obligation") is None:
                    data["obligation"] = {"rate": value, "application": None}
                else:
                    data["obligation"]["rate"] = value
            elif field == "threshold_amount" and data.get("threshold"):
                data["threshold"]["amount"] = value
            elif field == "contracted_price" and data.get("contracted_price"):
                data["contracted_price"]["amount"] = value
            elif field in {"notice_days", "discount_days", "net_days"}:
                data[field] = int(value)
            elif field == "expiry":
                data["expiry"] = value
                data["needs_confirmation"] = [item for item in data["needs_confirmation"] if item != "expiry"]
            else:
                data[field] = value
                data["needs_confirmation"] = [item for item in data["needs_confirmation"] if item != field]
            rescored = score_rule(
                RuleIR.model_validate(data),
                clauses[rule.source_clause_ids[0]].text,
                Decimal(self.settings(tenant_id).high_value_threshold),
            )
            updated.append(rescored)
        bundle.rules_json = _dump([rule.model_dump(mode="json") for rule in updated])
        bundle.test_run_id = ""
        return bundle

    def run_tests(self, tenant_id: str, bundle_id: str) -> dict:
        bundle = self._bundle(tenant_id, bundle_id)
        rules = self._rules(bundle)
        model = RecordingModel(bundle.supplier_key)
        bridge = ModelBridge(model)
        cases = []
        for rule in rules:
            if rule.needs_confirmation:
                continue
            cases.extend(template_cases(rule))
            bridge.complete(model_id=SONNET, system="test-agent", user=rule.rule_id, schema_name="AgentCases")
        judge = self._judge(bridge)
        report = run_suite(rules, cases, judge)
        bundle.test_run_id = report.run_id
        payload = report.model_dump(mode="json")
        self._audit(tenant_id, "system", "tests.ran", [bundle_id], {"run_id": report.run_id, "cases": len(report.results)})
        return payload

    def approve(
        self,
        tenant_id: str,
        bundle_id: str,
        actor: str,
        human_switches: dict[str, bool],
        waived: dict[str, str],
    ) -> BundleRow:
        bundle = self._bundle(tenant_id, bundle_id)
        rules = self._rules(bundle)
        if any(rule.needs_confirmation for rule in rules):
            raise PlatformError(409, "resolve ambiguous fields before approval")
        if not bundle.test_run_id:
            self.run_tests(tenant_id, bundle_id)
            rules = self._rules(bundle)
        report = run_suite(rules, [case for rule in rules for case in template_cases(rule)], self._judge(ModelBridge(RecordingModel(bundle.supplier_key))))
        for result in report.results:
            if result.case_id in waived:
                if result.author == "template":
                    raise PlatformError(409, "template cases cannot be waived")
                result.waived = True
                result.waive_reason = waived[result.case_id]
        if report.template_failures():
            raise PlatformError(409, "template tests are failing")
        switched: list[RuleIR] = []
        for rule in rules:
            required = bool(human_switches.get(rule.rule_id, False))
            if required and not rule.warned():
                raise PlatformError(409, "human review can be required only on a warned clause")
            switched.append(rule.model_copy(update={"human_required": required}))
        bundle.rules_json = _dump([rule.model_dump(mode="json") for rule in switched])
        previous = self._active(tenant_id, bundle.document_id)
        for row in self.session.scalars(select(BundleRow).where(BundleRow.document_id == bundle.document_id, BundleRow.tenant_id == tenant_id)).all():
            if row.id != bundle.id and row.active:
                row.active = 0
                row.status = "superseded"
        bundle.status = "approved"
        bundle.active = 1
        bundle.test_run_id = report.run_id
        self._rebuild_ledger(tenant_id, bundle)
        self._audit(
            tenant_id,
            actor,
            "bundle.approved",
            [bundle.id],
            {"version": bundle.version, "previous": previous.id if previous else None, "test_run_id": report.run_id},
        )
        return bundle

    def edit_contract(self, tenant_id: str, document_id: str, text: str | None, actor: str) -> BundleRow:
        document = self._document(tenant_id, document_id)
        active = self._active(tenant_id, document_id)
        if active is None:
            raise PlatformError(409, "approve an engine before editing it mid-period")
        if text:
            document.body = text
            document.sha256 = document_hash(text)
            document.status = "stored"
            return self.compile(tenant_id, document_id, actor)
        clone = BundleRow(
            id=uuid7(),
            tenant_id=tenant_id,
            document_id=document_id,
            version=self._next_version(tenant_id, document_id),
            status="draft",
            active=0,
            supplier_key=active.supplier_key,
            document_hash=active.document_hash,
            prompt_hash=active.prompt_hash,
            model_id=active.model_id,
            test_run_id="",
            rules_json=active.rules_json,
            clauses_json=active.clauses_json,
            embeddings_json=active.embeddings_json,
        )
        self.session.add(clone)
        self._audit(tenant_id, actor, "bundle.drafted", [clone.id], {"from": active.id})
        return clone

    def edit_clause_cascade(
        self,
        tenant_id: str,
        pack_id: str,
        child_document_id: str,
        text: str | None,
        actor: str,
        changed_sections: list[str] | None = None,
    ) -> dict:
        """Edit a clause in one pack document, recompile, and report the blast radius.

        The whole pack recompiles into a single draft bundle (rules for every
        document are regenerated). The clause network is then used to find, in a
        single hop, the clauses in *other* documents that reference what changed
        and the draft rules that derive from them - so a reviewer sees what to
        scrutinise before approving through the usual flow.
        """
        pack = self._pack(tenant_id, pack_id)
        child = self._document(tenant_id, child_document_id)
        if child.pack_id != pack.id:
            raise PlatformError(400, "document is not part of this pack")
        children = self._ordered_children(pack)
        index = next((position for position, row in enumerate(children, start=1) if row.id == child.id), None)
        if index is None:
            raise PlatformError(409, "cascade needs a multi-document pack with this document as a source")

        from compiler import segment_clauses

        old_sections = {clause.section: clause.text for clause in segment_clauses(child.body)}
        if text is not None and text != child.body:
            child.body = text
            child.sha256 = document_hash(text)
            child.status = "stored"
        new_sections = {clause.section: clause.text for clause in segment_clauses(child.body)}

        if changed_sections:
            touched = {str(section) for section in changed_sections}
        else:
            touched = {section for section, body in new_sections.items() if old_sections.get(section) != body}
            touched |= {section for section in old_sections if section not in new_sections}
        changed_clause_ids = {f"{index}.{section}" for section in touched}

        bundle = self._recompile_pack(tenant_id, pack, actor)

        network = self._pack_network(pack)
        cascade = cascade_targets(network, changed_clause_ids)
        affected = changed_clause_ids | set(cascade["impacted_clause_ids"])

        impacted_rules = [
            {
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "severity": rule.severity,
                "warned": rule.warned(),
                "source_clause_ids": rule.source_clause_ids,
                "reason": "edited" if set(rule.source_clause_ids) & changed_clause_ids else "cross-reference",
            }
            for rule in self._rules(bundle)
            if set(rule.source_clause_ids) & affected
        ]

        self._audit(
            tenant_id,
            actor,
            "clause.edited_cascade",
            [bundle.id],
            {
                "child_document_id": child.id,
                "changed": sorted(changed_clause_ids),
                "impacted_clauses": cascade["impacted_clause_ids"],
                "impacted_rules": [rule["rule_id"] for rule in impacted_rules],
            },
        )
        return {
            "bundle_id": bundle.id,
            "version": bundle.version,
            "status": bundle.status,
            "active": bool(bundle.active),
            "impact": {
                "document_id": pack.id,
                "child_document_id": child.id,
                "child_index": index,
                "changed_clause_ids": cascade["changed_clause_ids"],
                "impacted_clause_ids": cascade["impacted_clause_ids"],
                "impacted_rules": impacted_rules,
                "references": cascade["references"],
                "external": network.get("external", []),
            },
        }

    def _ordered_children(self, pack: DocumentRow) -> list[DocumentRow]:
        """Pack children in the same order _network_sources indexes them."""
        children = self._pack_files(pack.tenant_id, pack.id)
        ordered = sorted(children, key=lambda row: (PACK_KINDS.index(row.kind) if row.kind in PACK_KINDS else 99, row.filename))
        return [row for row in ordered if row.body.strip()]

    def set_human_switch(self, tenant_id: str, bundle_id: str, rule_id: str, required: bool, actor: str) -> RuleIR:
        bundle = self._bundle(tenant_id, bundle_id)
        if not bundle.active:
            raise PlatformError(409, "the human switch is changed on the live bundle")
        rules = self._rules(bundle)
        found = None
        updated = []
        for rule in rules:
            if rule.rule_id != rule_id:
                updated.append(rule)
                continue
            if required and not rule.warned():
                raise PlatformError(409, "only a warned clause can require a human")
            found = rule.model_copy(update={"human_required": required})
            updated.append(found)
        if found is None:
            raise PlatformError(404, "rule not found")
        bundle.rules_json = _dump([rule.model_dump(mode="json") for rule in updated])
        self._audit(tenant_id, actor, "clause.human_switch", [rule_id], {"required": required})
        return found

    def accept_event(self, tenant_id: str, event: Event, idempotency_key: str) -> dict:
        existing = self.session.get(IdempotencyRow, f"{tenant_id}:{idempotency_key}")
        if existing:
            return json.loads(existing.response_json)
        if self.session.get(TransactionRow, event.transaction_id):
            raise PlatformError(409, "transaction id already used")
        self.session.add(
            TransactionRow(
                id=event.transaction_id,
                tenant_id=tenant_id,
                supplier_key=event.supplier_key,
                event_type=event.event_type,
                payload_json=event.model_dump_json(),
                idempotency_key=idempotency_key,
            )
        )
        self._outbox(tenant_id, "TransactionAccepted", {"transaction_id": event.transaction_id, "event_type": event.event_type})
        evaluations = []
        bundles = self.session.scalars(
            select(BundleRow).where(
                BundleRow.tenant_id == tenant_id,
                BundleRow.supplier_key == event.supplier_key,
                BundleRow.active == 1,
            )
        ).all()
        for bundle in bundles:
            evaluations.extend(self._evaluate_bundle(tenant_id, bundle, event))
        response = {"transaction_id": event.transaction_id, "evaluations": evaluations}
        self.session.add(
            IdempotencyRow(key=f"{tenant_id}:{idempotency_key}", tenant_id=tenant_id, response_json=_dump(response))
        )
        return response

    def interpret_unstructured(self, tenant_id: str, text: str, supplier_key: str | None, on_progress=None) -> dict:
        if not llm_enabled():
            raise PlatformError(503, "the language model is not configured")
        try:
            client = chat_client_from_env()
            events = normalize_unstructured(text, client.complete, supplier_key, on_progress=on_progress)
        except LlmError as exc:
            raise PlatformError(503, exc.detail) from exc
        except NormalizeFailure as exc:
            raise PlatformError(422, exc.detail) from exc
        self._audit(
            tenant_id,
            "system",
            "invoice.interpreted",
            [event.transaction_id for event in events],
            {"count": len(events)},
        )
        results = []
        for index, event in enumerate(events, start=1):
            if on_progress:
                on_progress(
                    {
                        "index": index,
                        "total": len(events),
                        "detail": f"Checking transaction {index} of {len(events)} against the approved rules.",
                    }
                )
            results.append(self.accept_event(tenant_id, event, f"llm-{event.transaction_id}"))
        return {"accepted": len(results), "results": results}

    def _model_for_compile(self, supplier_key: str) -> RecordingModel | LlmCompiler:
        if not llm_enabled():
            return RecordingModel(supplier_key, SONNET)
        try:
            client = chat_client_from_env()
        except LlmError as exc:
            raise PlatformError(503, exc.detail) from exc
        return LlmCompiler(supplier_key, client.complete, client.model_id)

    def confirm_finding(self, tenant_id: str, finding_id: str, actor: str, accept: bool) -> FindingRow:
        row = self._finding(tenant_id, finding_id)
        row.status = "verified" if accept else "dismissed"
        if accept:
            row.booked = 1
        self._audit(tenant_id, actor, "finding.confirmed" if accept else "finding.dismissed", [finding_id], {})
        return row

    def investigate(self, tenant_id: str, finding_id: str) -> dict:
        finding = self._finding(tenant_id, finding_id)
        payload = json.loads(finding.payload_json)
        bundle = self._bundle(tenant_id, finding.bundle_id)
        clauses = self._clauses(bundle)
        tools = {
            "get_clause": lambda _args: [clause.model_dump(mode="json") for clause in clauses if clause.clause_id in payload.get("clause_ids", [])],
            "get_invoice_lines": lambda _args: payload.get("lines", []),
            "get_ledger": lambda _args: {"balance": payload.get("balance")},
            "search_clauses": lambda _args: [
                {"clause_id": row["clause_id"], "text": row["text"]}
                for row in search_clauses(
                    json.loads(bundle.embeddings_json)[0] if bundle.embeddings_json not in ("", "[]") else [],
                    self._embedding_rows(tenant_id, bundle),
                    tenant_id,
                    bundle.document_id,
                )
            ],
        }
        bridge = ModelBridge(RecordingModel(bundle.supplier_key))
        result = investigate_exception(
            bridge,
            {"finding_id": finding_id, "clause_ids": payload.get("clause_ids", []), "trace": payload.get("formula_trace")},
            SONNET,
            tools,
        )
        self.session.add(
            InvestigationRow(id=uuid7(), tenant_id=tenant_id, finding_id=finding_id, payload_json=_dump(result))
        )
        if finding.status != "awaiting_human":
            finding.status = "investigating"
        return result

    def promote_patch(self, tenant_id: str, document_id: str, rule: dict, actor: str) -> BundleRow:
        draft = self.edit_contract(tenant_id, document_id, None, actor)
        rules = self._rules(draft)
        rules.append(RuleIR.model_validate(rule))
        draft.rules_json = _dump([item.model_dump(mode="json") for item in rules])
        return draft

    def propose(self, tenant_id: str, finding_id: str, action_type: str, actor: str) -> dict:
        finding = self._finding(tenant_id, finding_id)
        if finding.status == "awaiting_human":
            raise PlatformError(409, "this clause is waiting for a human")
        settings = self.settings(tenant_id)
        action = propose_action(
            Action(
                action_id=uuid7(),
                tenant_id=tenant_id,
                finding_id=finding_id,
                action_type=action_type,  # type: ignore[arg-type]
                status="draft",
                requester=actor,
                risk="low",
                sod_required=bool(settings.sod_required),
                connector_write_scope=bool(settings.connector_write),
            ),
            finding.status,
        )
        if action.failure_reason:
            raise PlatformError(409, action.failure_reason)
        self.session.add(ActionRow(id=action.action_id, tenant_id=tenant_id, payload_json=_dump(action.__dict__)))
        self._audit(tenant_id, actor, "action.proposed", [action.action_id], {"type": action_type})
        return action.__dict__

    def decide_action(self, tenant_id: str, action_id: str, actor: str, accept: bool) -> dict:
        row = self.session.get(ActionRow, action_id)
        if row is None or row.tenant_id != tenant_id:
            raise PlatformError(404, "action not found")
        data = json.loads(row.payload_json)
        action = Action(**data)
        if not accept:
            action.status = "rejected"
        else:
            action = approve_action(action, actor)
            if action.failure_reason:
                raise PlatformError(409, action.failure_reason)
            action = execute_action(action)
            if action.failure_reason and action.status != "succeeded":
                raise PlatformError(409, action.failure_reason)
        row.payload_json = _dump(action.__dict__)
        self._audit(tenant_id, actor, "action.decided", [action_id], {"status": action.status})
        return action.__dict__

    def control_map(self, tenant_id: str, document_id: str) -> dict:
        bundle = self._active(tenant_id, document_id) or self._latest(tenant_id, document_id)
        if bundle is None:
            raise PlatformError(404, "no bundle")
        clauses = self._clauses(bundle)
        rules = self._rules(bundle)
        findings = self._findings_for_document(tenant_id, document_id)
        nodes = [
            {
                "id": f"contract:{document_id}",
                "column": "contract",
                "kind": "contract",
                "label": bundle.supplier_key,
                "data": {"version": bundle.version, "status": bundle.status},
            }
        ]
        edges = []
        for clause in clauses:
            if not clause.commercial:
                continue
            nodes.append(
                {
                    "id": f"clause:{clause.clause_id}",
                    "column": "clause",
                    "kind": "clause",
                    "label": clause.section,
                    "data": {"heading": clause.heading, "text": clause.text, "bbox": clause.bbox},
                }
            )
            edges.append({"source": f"contract:{document_id}", "target": f"clause:{clause.clause_id}", "label": "contains"})
        for rule in rules:
            ledger = self._ledger_row(tenant_id, bundle, rule)
            nodes.append(
                {
                    "id": f"rule:{rule.rule_id}",
                    "column": "rule",
                    "kind": rule.rule_type,
                    "label": rule.rule_type,
                    "data": {
                        "warned": rule.warned(),
                        "value_band": rule.value_band,
                        "risk_band": rule.risk_band,
                        "warning_reasons": rule.warning_reasons,
                        "human_required": rule.human_required,
                        "balance": ledger.balance if ledger else "0",
                        "threshold": str(rule.threshold.amount) if rule.threshold else None,
                        "clause_text": "\n".join(
                            next((clause.text for clause in clauses if clause.clause_id == clause_id), "")
                            for clause_id in rule.source_clause_ids
                        ).strip()
                        or rule.clause_text,
                        "needs_confirmation": rule.needs_confirmation,
                        "rate": str(rule.obligation.rate) if rule.obligation else None,
                        "application": rule.obligation.application if rule.obligation else None,
                        "sku": rule.sku,
                        "contracted_price": str(rule.contracted_price.amount) if rule.contracted_price else None,
                        "notice_days": rule.notice_days,
                        "expiry": rule.expiry.isoformat() if rule.expiry else None,
                        "discount_percent": None if rule.discount_percent is None else str(rule.discount_percent),
                        "discount_days": rule.discount_days,
                        "net_days": rule.net_days,
                        "penalty_rate": None if rule.penalty_rate is None else str(rule.penalty_rate),
                        "target": None if rule.target is None else str(rule.target),
                    },
                }
            )
            for clause_id in rule.source_clause_ids:
                edges.append({"source": f"clause:{clause_id}", "target": f"rule:{rule.rule_id}", "label": "compiled"})
        for finding in findings:
            if finding.bundle_id != bundle.id and bundle.active:
                continue
            nodes.append(
                {
                    "id": f"finding:{finding.id}",
                    "column": "outcome",
                    "kind": "finding",
                    "label": finding.amount,
                    "data": {
                        "status": finding.status,
                        "transaction_id": finding.transaction_id,
                        "currency": finding.currency,
                        "explanation": json.loads(finding.payload_json).get("explanation", ""),
                        "formula": (json.loads(finding.payload_json).get("formula_trace") or {}).get("formula", ""),
                    },
                }
            )
            edges.append({"source": f"rule:{finding.rule_id}", "target": f"finding:{finding.id}", "label": "produced"})
        replay = [
            json.loads(row.payload_json) | {"transaction_id": row.transaction_id, "seq": row.seq}
            for row in self.session.scalars(
                select(EvaluationRow).where(EvaluationRow.document_id == document_id, EvaluationRow.tenant_id == tenant_id).order_by(EvaluationRow.seq)
            ).all()
        ]
        return {
            "document_id": document_id,
            "bundle_id": bundle.id,
            "active": bool(bundle.active),
            "status": bundle.status,
            "nodes": nodes,
            "edges": edges,
            "replay": replay,
        }

    def clause_network(self, tenant_id: str, document_id: str) -> dict:
        """Cross-document clause reference graph for the spider-web view."""
        pack = self._document(tenant_id, document_id)
        bundle = self._active(tenant_id, document_id) or self._latest(tenant_id, document_id)
        if bundle is None:
            raise PlatformError(404, "no bundle")
        network = self._pack_network(pack)
        return {
            "document_id": document_id,
            "bundle_id": bundle.id,
            "supplier_key": bundle.supplier_key,
            "active": bool(bundle.active),
            "status": bundle.status,
            **network,
        }

    def _pack_network(self, pack: DocumentRow) -> dict:
        """Build the cross-document clause graph from a pack's source documents."""
        from compiler.pipeline import is_boilerplate

        from compiler import segment_clauses

        sources = self._network_sources(pack)
        documents = []
        clause_inputs = []
        for index, (kind, filename, body) in enumerate(sources, start=1):
            documents.append({"index": index, "kind": kind, "filename": filename, "title": _document_title(body)})
            # Segment each source on its own so a document's clauses are attributed
            # to that document, not bled into the previous one after flattening.
            for clause in segment_clauses(body):
                clause_inputs.append(
                    {
                        "clause_id": f"{index}.{clause.section}",
                        "section": clause.section,
                        "heading": clause.heading,
                        "text": clause.text,
                        "commercial": not is_boilerplate(clause),
                        "document_index": index,
                    }
                )
        return build_clause_network(documents, clause_inputs)  # type: ignore[arg-type]

    def _network_sources(self, pack: DocumentRow) -> list[tuple[str, str, str]]:
        """Read-only view of the pack's source documents in compile order."""
        children = self._pack_files(pack.tenant_id, pack.id)
        if children:
            ordered = sorted(children, key=lambda row: (PACK_KINDS.index(row.kind) if row.kind in PACK_KINDS else 99, row.filename))
            return [(row.kind, row.filename, row.body) for row in ordered if row.body.strip()]
        if pack.body.strip():
            return [(pack.kind if pack.kind in PACK_KINDS else "contract", pack.filename, pack.body)]
        return []

    def portfolio(self, tenant_id: str) -> dict:
        nodes = []
        edges = []
        documents = self.session.scalars(select(DocumentRow).where(DocumentRow.tenant_id == tenant_id)).all()
        for document in documents:
            spend = self._supplier_spend(tenant_id, document.supplier_key)
            risk = self._supplier_risk(tenant_id, document.id)
            nodes.append(
                {
                    "id": document.supplier_key,
                    "label": document.supplier_key,
                    "spend": str(spend),
                    "amount_at_risk": str(risk),
                }
            )
            edges.append({"source": document.supplier_key, "target": document.id, "label": "contract"})
            nodes.append({"id": document.id, "label": document.filename, "spend": "0", "amount_at_risk": "0"})
        return {"nodes": nodes, "edges": edges}

    def roi(self, tenant_id: str) -> dict:
        invoices = self.session.scalars(
            select(TransactionRow).where(TransactionRow.tenant_id == tenant_id, TransactionRow.event_type == "invoice.posted")
        ).all()
        spend = Decimal("0")
        for row in invoices:
            invoice = Invoice.model_validate_json(row.payload_json)
            spend += invoice.total.amount
        findings = self.session.scalars(select(FindingRow).where(FindingRow.tenant_id == tenant_id)).all()
        open_amount = Decimal("0")
        waiting = Decimal("0")
        verified = Decimal("0")
        for finding in findings:
            amount = Decimal(finding.amount or "0")
            if finding.status == "dismissed":
                continue
            if finding.status == "awaiting_human":
                waiting += amount
            open_amount += amount
            if finding.status == "verified" and finding.booked:
                verified += amount
        recovered = Decimal("0")
        for row in self.session.scalars(select(ActionRow).where(ActionRow.tenant_id == tenant_id)).all():
            action = json.loads(row.payload_json)
            if action.get("status") == "succeeded":
                finding = self.session.get(FindingRow, action["finding_id"])
                if finding and finding.booked:
                    recovered += Decimal(finding.amount or "0")
        cleared = 0
        for row in invoices:
            evals = self.session.scalars(select(EvaluationRow).where(EvaluationRow.transaction_id == row.id)).all()
            if evals and all(json.loads(item.payload_json)["outcome"] in {"pass", "skipped"} for item in evals):
                cleared += 1
        minutes = Decimal(self.settings(tenant_id).review_minutes)
        hours = (Decimal(cleared) * minutes) / Decimal("60")
        return {
            "spend_monitored": str(spend),
            "invoices_processed": len(invoices),
            "invoices_cleared": cleared,
            "exceptions_open": sum(1 for item in findings if item.status in {"open", "awaiting_human", "investigating"}),
            "amount_at_risk": str(open_amount),
            "amount_waiting_human": str(waiting),
            "amount_verified": str(verified),
            "amount_recovered": str(recovered),
            "review_hours_avoided": str(hours.quantize(Decimal("0.01"))),
        }

    def audit_entries(self, tenant_id: str) -> list[dict]:
        rows = self.session.scalars(select(AuditRowModel).where(AuditRowModel.tenant_id == tenant_id).order_by(AuditRowModel.seq)).all()
        return [
            {
                "seq": row.seq,
                "prev_hash": row.prev_hash,
                "row_hash": row.row_hash,
                "event": json.loads(row.payload_json),
            }
            for row in rows
        ]

    def replay_diff(self, tenant_id: str, bundle_id: str) -> dict:
        bundle = self._bundle(tenant_id, bundle_id)
        rules = self._rules(bundle)
        added = []
        for row in self._transactions(tenant_id, bundle.supplier_key):
            event = _events.validate_json(row.payload_json)
            balance: dict[str, Decimal] = {}
            for rule in rules:
                if rule.kind == "natural_language":
                    continue
                before = balance.get(rule.rule_id, ZERO)
                evaluation, delta = evaluate_condition(rule, event, before)
                balance[rule.rule_id] = before + delta
                if evaluation.outcome == "violation":
                    added.append(
                        {
                            "transaction_id": event.transaction_id,
                            "rule_id": rule.rule_id,
                            "amount": str(evaluation.amount_at_risk.amount if evaluation.amount_at_risk else 0),
                        }
                    )
        current = [
            {"transaction_id": row.transaction_id, "rule_id": row.rule_id, "amount": row.amount}
            for row in self._findings_for_document(tenant_id, bundle.document_id)
            if row.status != "dismissed"
        ]
        return {"proposed": added, "current": current, "live_version_unchanged": True}

    def retention_delete(self, tenant_id: str, actor: str) -> None:
        for model in (
            DocumentRow,
            BundleRow,
            TransactionRow,
            LedgerRow,
            EvaluationRow,
            FindingRow,
            ActionRow,
            OutboxRow,
            InvestigationRow,
            IdempotencyRow,
            ApiKeyRow,
        ):
            self.session.query(model).filter(model.tenant_id == tenant_id).delete()
        self._audit(tenant_id, actor, "tenant.deleted", [tenant_id], {})

    def _evaluate_bundle(self, tenant_id: str, bundle: BundleRow, event: Event) -> list[dict]:
        results = []
        document = self._document(tenant_id, bundle.document_id)
        effective = date.fromisoformat(document.effective_date)
        bridge = ModelBridge(RecordingModel(bundle.supplier_key))
        seq = self.session.query(EvaluationRow).count() + 1
        for rule in self._rules(bundle):
            period = rule.period
            pkey = period_key(period, _event_date(event), effective) if period else "none"
            ledger = self._ensure_ledger(tenant_id, bundle, rule, pkey, _currency(event))
            balance_before = Decimal(ledger.balance)
            if rule.kind == "natural_language" or rule.rule_type == "natural_language":
                if not natural_language_applicable(rule, event):
                    evaluation = judge_skip(rule)
                else:
                    self._outbox(
                        tenant_id,
                        "NaturalLanguageRuleInvoked",
                        {"rule_id": rule.rule_id, "transaction_id": event.transaction_id},
                    )
                    evaluation = judge_natural_language(bridge, rule, json.loads(event.model_dump_json()), SONNET)
                delta = ZERO
            else:
                evaluation, delta = evaluate_condition(rule, event, balance_before)
                if event.transaction_id not in json.loads(ledger.applied_json) and delta != 0:
                    applied = json.loads(ledger.applied_json)
                    applied.append(event.transaction_id)
                    ledger.applied_json = _dump(applied)
                    ledger.balance = str(balance_before + delta)
                    ledger.version += 1
                elif event.transaction_id not in json.loads(ledger.applied_json) and delta == 0 and rule.rule_type == "threshold_rebate":
                    applied = json.loads(ledger.applied_json)
                    applied.append(event.transaction_id)
                    ledger.applied_json = _dump(applied)
            row_id = uuid7()
            self.session.add(
                EvaluationRow(
                    id=row_id,
                    tenant_id=tenant_id,
                    document_id=bundle.document_id,
                    bundle_id=bundle.id,
                    transaction_id=event.transaction_id,
                    rule_id=rule.rule_id,
                    payload_json=evaluation.model_dump_json(),
                    seq=seq,
                )
            )
            seq += 1
            if evaluation.outcome in {"violation", "escalate"}:
                self._open_finding(tenant_id, bundle, rule, event, evaluation, balance_before)
            if evaluation.outcome == "escalate" and rule.kind == "condition":
                self._outbox(tenant_id, "FindingEscalated", {"rule_id": rule.rule_id, "transaction_id": event.transaction_id})
            results.append(json.loads(evaluation.model_dump_json()))
        return results

    def _open_finding(self, tenant_id, bundle, rule: RuleIR, event: Event, evaluation, balance_before: Decimal) -> None:
        amount = evaluation.amount_at_risk.amount if evaluation.amount_at_risk else Decimal("0")
        currency = evaluation.amount_at_risk.currency if evaluation.amount_at_risk else "USD"
        status = "open"
        if rule.human_required:
            status = "awaiting_human"
        elif evaluation.outcome == "escalate":
            status = "investigating"
        booked = 0 if evaluation.amount_estimated else 1
        payload = {
            "clause_ids": rule.source_clause_ids,
            "explanation": evaluation.explanation,
            "formula_trace": evaluation.formula_trace.model_dump(mode="json"),
            "balance": str(balance_before),
            "invoice_number": getattr(event, "invoice_number", None),
            "lines": [line.model_dump(mode="json") for line in getattr(event, "lines", [])],
        }
        self.session.add(
            FindingRow(
                id=uuid7(),
                tenant_id=tenant_id,
                document_id=bundle.document_id,
                bundle_id=bundle.id,
                version=bundle.version,
                rule_id=rule.rule_id,
                transaction_id=event.transaction_id,
                status=status,
                amount=str(amount),
                currency=currency,
                estimated=1 if evaluation.amount_estimated else 0,
                booked=booked,
                payload_json=_dump(payload),
            )
        )

    def _rebuild_ledger(self, tenant_id: str, bundle: BundleRow) -> None:
        self.session.query(LedgerRow).filter(
            LedgerRow.document_id == bundle.document_id, LedgerRow.tenant_id == tenant_id
        ).delete()
        document = self._document(tenant_id, bundle.document_id)
        effective = date.fromisoformat(document.effective_date)
        for row in self._transactions(tenant_id, bundle.supplier_key):
            event = _events.validate_json(row.payload_json)
            for rule in self._rules(bundle):
                if rule.kind == "natural_language" or rule.rule_type == "natural_language":
                    continue
                pkey = period_key(rule.period, _event_date(event), effective) if rule.period else "none"
                ledger = self._ensure_ledger(tenant_id, bundle, rule, pkey, _currency(event))
                before = Decimal(ledger.balance)
                _evaluation, delta = evaluate_condition(rule, event, before)
                applied = json.loads(ledger.applied_json)
                if event.transaction_id in applied:
                    continue
                applied.append(event.transaction_id)
                ledger.applied_json = _dump(applied)
                ledger.balance = str(before + delta)
                ledger.version += 1

    def _judge(self, bridge: ModelBridge):
        def _inner(rule, event, balance):
            return judge_natural_language(bridge, rule, json.loads(event.model_dump_json()), SONNET)

        return _inner

    def _document(self, tenant_id: str, document_id: str) -> DocumentRow:
        row = self.session.get(DocumentRow, document_id)
        if row is None or row.tenant_id != tenant_id:
            raise PlatformError(404, "contract not found")
        return row

    def _pack(self, tenant_id: str, pack_id: str) -> DocumentRow:
        row = self._document(tenant_id, pack_id)
        if row.pack_id not in {"", row.id}:
            raise PlatformError(404, "pack not found")
        return row

    def _pack_files(self, tenant_id: str, pack_id: str) -> list[DocumentRow]:
        rows = self.session.scalars(select(DocumentRow).where(DocumentRow.tenant_id == tenant_id, DocumentRow.pack_id == pack_id)).all()
        return [row for row in rows if row.id != pack_id]

    def _pack_sources(self, pack: DocumentRow) -> list[tuple[str, str, str]]:
        children = self._pack_files(pack.tenant_id, pack.id)
        if pack.kind != "pack" and pack.body.strip() and not children:
            return [(pack.kind or "contract", pack.filename, pack.body)]
        if pack.kind != "pack" and pack.body.strip():
            self.add_pack_file(pack.tenant_id, pack.id, pack.kind or "contract", pack.filename, pack.content_type, pack.body, pack.storage_uri)
            pack.kind = "pack"
            children = self._pack_files(pack.tenant_id, pack.id)
        ordered = sorted(children, key=lambda row: (PACK_KINDS.index(row.kind) if row.kind in PACK_KINDS else 99, row.filename))
        return [(row.kind, row.filename, row.body) for row in ordered if row.body.strip()]

    def _bundle(self, tenant_id: str, bundle_id: str) -> BundleRow:
        row = self.session.get(BundleRow, bundle_id)
        if row is None or row.tenant_id != tenant_id:
            raise PlatformError(404, "bundle not found")
        return row

    def _finding(self, tenant_id: str, finding_id: str) -> FindingRow:
        row = self.session.get(FindingRow, finding_id)
        if row is None or row.tenant_id != tenant_id:
            raise PlatformError(404, "finding not found")
        return row

    def _active(self, tenant_id: str, document_id: str) -> BundleRow | None:
        return self.session.scalar(
            select(BundleRow).where(BundleRow.tenant_id == tenant_id, BundleRow.document_id == document_id, BundleRow.active == 1)
        )

    def _latest(self, tenant_id: str, document_id: str) -> BundleRow | None:
        return self.session.scalar(
            select(BundleRow)
            .where(BundleRow.tenant_id == tenant_id, BundleRow.document_id == document_id)
            .order_by(BundleRow.version.desc())
        )

    def _next_version(self, tenant_id: str, document_id: str) -> int:
        latest = self._latest(tenant_id, document_id)
        return 1 if latest is None else latest.version + 1

    def _rules(self, bundle: BundleRow) -> list[RuleIR]:
        rules: list[RuleIR] = []
        changed = False
        for item in json.loads(bundle.rules_json):
            rule = RuleIR.model_validate(item)
            trigger = engine_triggers(rule.rule_type, list(rule.trigger))
            if list(rule.trigger) != trigger:
                rule = rule.model_copy(update={"trigger": trigger})
                changed = True
            rules.append(rule)
        if changed:
            bundle.rules_json = _dump([rule.model_dump(mode="json") for rule in rules])
        return rules

    def _clauses(self, bundle: BundleRow) -> list[Clause]:
        return [Clause.model_validate(item) for item in json.loads(bundle.clauses_json)]

    def _ensure_ledger(self, tenant_id, bundle, rule: RuleIR, pkey: str, currency: str) -> LedgerRow:
        metric = rule.threshold.metric if rule.threshold else rule.rule_type
        row_id = f"{tenant_id}:{bundle.document_id}:{rule.rule_id}:{pkey}:{metric}"
        row = self.session.get(LedgerRow, row_id)
        if row is None:
            row = LedgerRow(
                id=row_id,
                tenant_id=tenant_id,
                supplier_key=bundle.supplier_key,
                document_id=bundle.document_id,
                rule_id=rule.rule_id,
                period_key=pkey,
                metric=metric,
                balance="0",
                currency=currency,
                applied_json="[]",
                version=0,
            )
            self.session.add(row)
            self.session.flush()
        return row

    def _ledger_row(self, tenant_id, bundle, rule: RuleIR) -> LedgerRow | None:
        return self.session.scalar(
            select(LedgerRow).where(LedgerRow.tenant_id == tenant_id, LedgerRow.document_id == bundle.document_id, LedgerRow.rule_id == rule.rule_id)
        )

    def _findings_for_document(self, tenant_id: str, document_id: str) -> list[FindingRow]:
        return list(self.session.scalars(select(FindingRow).where(FindingRow.tenant_id == tenant_id, FindingRow.document_id == document_id)).all())

    def _transactions(self, tenant_id: str, supplier_key: str) -> list[TransactionRow]:
        return list(
            self.session.scalars(
                select(TransactionRow).where(TransactionRow.tenant_id == tenant_id, TransactionRow.supplier_key == supplier_key)
            ).all()
        )

    def _supplier_spend(self, tenant_id: str, supplier_key: str) -> Decimal:
        total = Decimal("0")
        for row in self._transactions(tenant_id, supplier_key):
            if row.event_type != "invoice.posted":
                continue
            total += Invoice.model_validate_json(row.payload_json).total.amount
        return total

    def _supplier_risk(self, tenant_id: str, document_id: str) -> Decimal:
        total = Decimal("0")
        for row in self._findings_for_document(tenant_id, document_id):
            if row.status != "dismissed":
                total += Decimal(row.amount or "0")
        return total

    def _embedding_rows(self, tenant_id: str, bundle: BundleRow) -> list[dict]:
        clauses = self._clauses(bundle)
        vectors = json.loads(bundle.embeddings_json or "[]")
        rows = []
        for clause, vector in zip(clauses, vectors, strict=False):
            rows.append(
                {
                    "tenant_id": tenant_id,
                    "document_id": bundle.document_id,
                    "clause_id": clause.clause_id,
                    "text": clause.text,
                    "embedding": vector,
                }
            )
        return rows

    def _audit(self, tenant_id: str, actor: str, action: str, refs: list[str], payload: dict) -> None:
        log = self._audit_cache.setdefault(tenant_id, AuditLog())
        for row in self.session.scalars(select(AuditRowModel).where(AuditRowModel.tenant_id == tenant_id).order_by(AuditRowModel.seq)).all():
            if len(log) >= row.seq:
                continue
            event = AuditEvent.model_validate(json.loads(row.payload_json))
            log.append(event)
        event = AuditEvent(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            object_refs=refs,
            correlation_id=uuid7(),
            payload=payload,
        )
        chained = log.append(event)
        self.session.add(
            AuditRowModel(
                tenant_id=tenant_id,
                prev_hash=chained.prev_hash,
                row_hash=chained.row_hash,
                payload_json=event.model_dump_json(),
            )
        )

    def _outbox(self, tenant_id: str, event_type: str, payload: dict) -> None:
        self.session.add(
            OutboxRow(event_id=uuid7(), tenant_id=tenant_id, event_type=event_type, payload_json=_dump(payload), published=0)
        )


def judge_skip(rule: RuleIR):
    from glasswing_domain.evaluation import Evaluation

    return Evaluation(rule_id=rule.rule_id, outcome="skipped", explanation="trigger did not match", model_called=False)


def _dump(value) -> str:
    return json.dumps(value)


def _source_heading(kind: str, filename: str) -> str:
    label = KIND_LABELS.get(kind)
    if not label:
        return filename
    return f"{label} ({filename})"


def _prepare_source(index: int, heading: str, body: str) -> str:
    namespaced = _HEADING_LINE.sub(
        lambda match: f"{index}.{match.group('section')}{match.group('dot')}{match.group('space')}",
        body.strip(),
    )
    if _HEADING_LINE.search(namespaced):
        return namespaced
    return f"{index}. {heading}\n{body.strip()}"


def _supplier_from_text(text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("supplier:"):
            return line.split(":", 1)[1].strip().lower().replace(" ", "-")
    return "unknown"


def _document_title(body: str) -> str:
    """First meaningful line of a document, used as a citable title."""
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("supplier:", "buyer:", "effective date:", "currency:", "contract year:")):
            continue
        return stripped[:120]
    return ""


def _event_date(event: Event) -> date:
    if isinstance(event, Invoice):
        return event.invoice_date
    if isinstance(event, SpendEvent):
        return event.effective_on
    if isinstance(event, PerformanceEvent):
        return event.reported_on
    return event.as_of


def _currency(event: Event) -> str:
    if isinstance(event, Invoice):
        return event.currency
    if isinstance(event, SpendEvent):
        return event.amount.currency
    if isinstance(event, PerformanceEvent) and event.period_spend:
        return event.period_spend.currency
    return "USD"


def money(amount: str, currency: str = "USD") -> Money:
    return Money(amount=Decimal(amount), currency=currency)
