"""Append-only hash-chained audit log. No update or delete API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from glasswing_domain.events import AuditEvent


@dataclass(frozen=True)
class AuditRow:
    seq: int
    event: AuditEvent
    prev_hash: str
    row_hash: str


class AuditLog:
    def __init__(self) -> None:
        self._rows: list[AuditRow] = []

    def append(self, event: AuditEvent) -> AuditRow:
        prev = self._rows[-1].row_hash if self._rows else "0" * 64
        payload = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        row_hash = hashlib.sha256(f"{prev}{payload}".encode()).hexdigest()
        row = AuditRow(seq=len(self._rows) + 1, event=event, prev_hash=prev, row_hash=row_hash)
        self._rows.append(row)
        return row

    def verify(self) -> bool:
        prev = "0" * 64
        for row in self._rows:
            payload = json.dumps(row.event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            expected = hashlib.sha256(f"{prev}{payload}".encode()).hexdigest()
            if row.prev_hash != prev or row.row_hash != expected:
                return False
            prev = row.row_hash
        return True

    def list_for_tenant(self, tenant_id: str) -> list[AuditRow]:
        return [row for row in self._rows if row.event.tenant_id == tenant_id]

    def __len__(self) -> int:
        return len(self._rows)
