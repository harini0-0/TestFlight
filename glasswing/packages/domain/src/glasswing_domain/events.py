"""Domain events exchanged between services. Schemas are the contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from glasswing_domain.ids import uuid7


class DomainEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=uuid7)
    event_type: str
    tenant_id: str
    correlation_id: str
    payload: dict[str, Any]


class ContractDocumentStored(DomainEvent):
    event_type: Literal["ContractDocumentStored"] = "ContractDocumentStored"


class TransactionAccepted(DomainEvent):
    event_type: Literal["TransactionAccepted"] = "TransactionAccepted"


class FindingEscalated(DomainEvent):
    event_type: Literal["FindingEscalated"] = "FindingEscalated"


class NaturalLanguageRuleInvoked(DomainEvent):
    event_type: Literal["NaturalLanguageRuleInvoked"] = "NaturalLanguageRuleInvoked"


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=uuid7)
    tenant_id: str
    actor: str
    action: str
    object_refs: list[str]
    correlation_id: str
    payload: dict[str, Any]
