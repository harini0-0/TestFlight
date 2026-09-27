"""Read an invoice without a language model.

Stage 1 compiles with the local engine when no model key is set. Stage 4 uses this
reader for the same case: part numbers, quantities, and prices already printed on the page.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from glasswing_domain.money import Money
from glasswing_domain.transactions import Invoice, InvoiceLine

_PART = re.compile(
    r"(?m)^[ \t]*((?:[A-Z]{1,4}\d{0,4}-\d{5})|(?:\d{3}-\d{5})|(?:\d{8,}[A-Z][A-Z0-9]*))\b"
)
_TAIL = re.compile(
    r"(\d+)\s+([\d,]+\.\d{2})\s+(\d+(?:\.\d+)?%)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
    re.S,
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def invoices_from_text(text: str, supplier_key: str | None) -> list[Invoice]:
    """Turn one printed invoice into a single posted event. Empty when no priced lines are found."""
    supplier = (supplier_key or "").strip() or "supplier"
    number = _invoice_number(text)
    if not number:
        return []
    lines = _lines(text)
    if not lines:
        return []
    return [
        Invoice(
            transaction_id=number,
            supplier_key=supplier,
            invoice_number=number,
            invoice_date=_invoice_date(text),
            lines=lines,
        )
    ]


def _invoice_number(text: str) -> str:
    match = re.search(r"invoice number\s+([A-Za-z0-9-]+)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"\binvoice\s+#?\s*([A-Za-z0-9-]{4,})", text, re.I)
    return match.group(1) if match else ""


def _invoice_date(text: str) -> date:
    match = re.search(r"invoice date\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if match:
        month = _MONTHS.get(match.group(2).lower())
        if month:
            return date(int(match.group(3)), month, int(match.group(1)))
    match = re.search(r"invoice date\s+(\d{4})-(\d{2})-(\d{2})", text, re.I)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return date.today()


def _lines(text: str) -> list[InvoiceLine]:
    matches = list(_PART.finditer(text))
    lines: list[InvoiceLine] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        sku = match.group(1)
        if sku in seen:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[match.end() : end]
        tail = _TAIL.search(chunk)
        if tail is None:
            continue
        seen.add(sku)
        description = re.sub(r"\s+", " ", chunk[: tail.start()]).strip()
        quantity = Decimal(tail.group(1))
        unit = _decimal(tail.group(4))
        extended = _decimal(tail.group(5))
        lines.append(
            InvoiceLine(
                sku=sku,
                description=description,
                category="goods",
                quantity=quantity,
                unit_price=Money(amount=unit, currency="USD"),
                extended_amount=Money(amount=extended, currency="USD"),
            )
        )
    return lines


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))
