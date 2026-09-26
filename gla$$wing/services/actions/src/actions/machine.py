"""Outbound actions. High-risk ERP writes cannot execute without an approval row."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActionType = Literal["notify_internal", "draft_supplier_dispute", "open_ticket", "erp_adjustment"]
ActionStatus = Literal["draft", "pending_approval", "approved", "executing", "succeeded", "failed", "rejected", "cancelled"]

RISK = {
    "notify_internal": "low",
    "draft_supplier_dispute": "medium",
    "open_ticket": "medium",
    "erp_adjustment": "high",
}

WRITE_SCOPE = "erp:write"


@dataclass
class Action:
    action_id: str
    tenant_id: str
    finding_id: str
    action_type: ActionType
    status: ActionStatus
    requester: str
    risk: str
    draft_body: str = ""
    dry_run_diff: dict = field(default_factory=dict)
    approver: str | None = None
    connector_write_scope: bool = False
    sod_required: bool = True
    failure_reason: str | None = None


def propose(action: Action, finding_status: str) -> Action:
    if finding_status == "awaiting_human":
        action.status = "failed"
        action.failure_reason = "finding is waiting for a human on this clause"
        return action
    action.risk = RISK[action.action_type]
    if action.action_type == "notify_internal":
        action.status = "succeeded"
        return action
    if action.action_type == "draft_supplier_dispute":
        action.status = "draft"
        if not action.draft_body:
            action.draft_body = (
                "We identified a variance against the contracted commercial terms. "
                "Please issue a credit for the amount in the attached calculation."
            )
        return action
    if action.action_type == "open_ticket":
        action.status = "pending_approval"
        return action
    action.status = "pending_approval"
    action.dry_run_diff = propose_change(action)
    return action


def propose_change(action: Action) -> dict:
    """Phase-1 connector. Records the diff and does not write to an ERP."""
    return {
        "system": "erp",
        "operation": "adjustment",
        "finding_id": action.finding_id,
        "mode": "dry_run",
        "applied": False,
    }


def approve(action: Action, approver: str, grant_write: bool = False) -> Action:
    if action.status not in {"draft", "pending_approval"}:
        action.failure_reason = f"cannot approve from {action.status}"
        return action
    if action.risk == "high":
        if action.sod_required and approver == action.requester:
            action.failure_reason = "segregation of duties: approver must differ from requester"
            return action
        if not action.connector_write_scope and not grant_write:
            action.failure_reason = "connector lacks erp write scope"
            return action
    action.approver = approver
    action.status = "approved"
    return action


def execute(action: Action) -> Action:
    if action.risk == "high" and action.status != "approved":
        action.status = "failed"
        action.failure_reason = "high-risk action requires approval before execution"
        return action
    if action.action_type == "erp_adjustment":
        action.dry_run_diff = propose_change(action)
        action.status = "succeeded"
        return action
    if action.status == "draft" and action.action_type == "draft_supplier_dispute":
        action.failure_reason = "drafts are not sent automatically"
        return action
    action.status = "succeeded"
    return action
