"""Parse a model reply that is supposed to be one JSON object."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any


def extract_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned, parse_float=Decimal)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1], parse_float=Decimal)
        raise ValueError("model output was not JSON") from None
