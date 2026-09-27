"""Local Appendix C price check used when no language model is configured."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

_CENT = Decimal("0.01")
_FEE = Decimal("1.0075")
_MICROSOFT = Decimal("0.835")
_ADOBE = Decimal("0.94")
_LIST = re.compile(r"(?:level d price|list price)\s+([0-9]+(?:\.[0-9]+)?)", re.I)


def is_dir_price_index(text: str) -> bool:
    lowered = text.lower()
    return (
        "level d less" in lowered
        and "16.50" in lowered
        and "administrative fee" in lowered
        and "customer price" in lowered
    )


def judge_dir_price(clause_id: str, clause_text: str, transaction: dict[str, Any]) -> dict[str, Any] | None:
    """Return a judgment when the clause is the DIR pricing index. None for every other clause."""
    if not is_dir_price_index(clause_text or ""):
        return None
    leaks: list[str] = []
    clean: list[str] = []
    total = Decimal("0.00")
    compared = 0
    for line in transaction.get("lines") or []:
        if not isinstance(line, dict):
            continue
        description = str(line.get("description") or "")
        basis = _basis(description)
        listed = _LIST.search(description)
        unit = _money(line.get("unit_price"))
        quantity = _quantity(line.get("quantity"))
        if basis is None or listed is None or unit is None or quantity is None:
            continue
        compared += 1
        label, concession, keep = basis
        list_price = Decimal(listed.group(1))
        expected = _round(list_price * (Decimal("1") - concession) * keep * _FEE)
        gap = _round(unit - expected)
        name = str(line.get("sku") or label)
        if gap > _CENT:
            amount = _round(gap * quantity)
            total += amount
            leaks.append(
                f"{name} ({label}) is billed at {unit} against a Level D or list price of {list_price}. "
                f"The contract price is { _formula(list_price, concession, keep) } = {expected}. "
                f"{quantity} x {gap} overcharges {amount}."
            )
        else:
            clean.append(f"{name} ({label}) at {unit} matches {expected}")
    if compared == 0:
        return {
            "outcome": "pass",
            "explanation": "No invoice line printed both a Level D or list price and a unit price to compare with Appendix C.",
            "evidence_refs": [clause_id],
            "estimated_amount": None,
        }
    if total > _CENT:
        kept = f" Within the contract: {'; '.join(clean)}." if clean else ""
        return {
            "outcome": "violation",
            "explanation": " ".join(leaks) + kept + f" Leakage { _round(total) } USD.",
            "evidence_refs": [clause_id],
            "estimated_amount": str(_round(total)),
        }
    return {
        "outcome": "pass",
        "explanation": "Each comparable line is at or under the Appendix C price, including the 0.75 percent administrative fee.",
        "evidence_refs": [clause_id],
        "estimated_amount": None,
    }


def _basis(description: str) -> tuple[str, Decimal, Decimal] | None:
    """Match the product on the line. The page footer names both publishers on every line."""
    lowered = description.lower()
    if "office professional" in lowered or "office standard" in lowered:
        return ("Office Professional/Standard", Decimal("0.075"), _MICROSOFT)
    if "windows pro" in lowered:
        return ("Windows Pro desktop operating system", Decimal("0.075"), _MICROSOFT)
    if "additional product" in lowered or "additional ea" in lowered:
        return ("additional EA licensing", Decimal("0"), _MICROSOFT)
    if "core cal" in lowered or "enterprise cal" in lowered:
        return ("Core CAL/Enterprise CAL Suite", Decimal("0.06"), _MICROSOFT)
    if "acrobat" in lowered or "adobe" in lowered:
        return ("Adobe", Decimal("0"), _ADOBE)
    return None


def _formula(list_price: Decimal, concession: Decimal, keep: Decimal) -> str:
    parts = [str(list_price)]
    if concession:
        parts.append(str(Decimal("1") - concession))
    parts.append(str(keep))
    parts.append("1.0075")
    return " x ".join(parts)


def _money(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        raw = value.get("amount")
    else:
        raw = value
    if raw in (None, ""):
        return None
    return Decimal(str(raw))


def _quantity(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)
