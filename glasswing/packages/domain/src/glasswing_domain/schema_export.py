"""JSON Schema exported from the Pydantic models."""

from __future__ import annotations

import json

from glasswing_domain.rules import RuleIR
from glasswing_domain.transactions import Invoice


def export_schemas() -> dict[str, object]:
    return {
        "RuleIR": RuleIR.model_json_schema(),
        "Invoice": Invoice.model_json_schema(),
    }


def dumps() -> str:
    return json.dumps(export_schemas(), indent=2)
