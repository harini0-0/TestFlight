"""Phase-1 connectors. They emit canonical events and never leak ERP field names."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from glasswing_domain.money import Money
from glasswing_domain.transactions import Invoice, InvoiceLine


def invoice_from_row(row: dict[str, str], transaction_id: str) -> Invoice:
    quantity = Decimal(row.get("quantity") or "1")
    unit = Decimal(row["unit_price"])
    extended = Decimal(row["extended_amount"]) if row.get("extended_amount") else unit * quantity
    rebate = row.get("rebate_amount")
    return Invoice(
        transaction_id=transaction_id,
        supplier_key=row["supplier_key"],
        invoice_number=row["invoice_number"],
        invoice_date=date.fromisoformat(row["invoice_date"]),
        currency=row.get("currency") or "USD",
        lines=[
            InvoiceLine(
                sku=row.get("sku") or None,
                description=row.get("description") or "",
                category=row.get("category") or "goods",
                quantity=quantity,
                unit_price=Money(amount=unit, currency=row.get("currency") or "USD"),
                extended_amount=Money(amount=extended, currency=row.get("currency") or "USD"),
                rebate_amount=Money(amount=Decimal(rebate), currency="USD") if rebate else None,
            )
        ],
    )


def invoices_from_csv(payload: str) -> list[Invoice]:
    reader = csv.DictReader(io.StringIO(payload))
    invoices: list[Invoice] = []
    for index, row in enumerate(reader, start=1):
        invoices.append(invoice_from_row(row, row.get("transaction_id") or f"csv-{index}"))
    return invoices


def invoices_from_directory(folder: Path) -> list[Invoice]:
    """Local stand-in for an SFTP drop."""
    found: list[Invoice] = []
    for path in sorted(folder.glob("*.csv")):
        found.extend(invoices_from_csv(path.read_text(encoding="utf-8")))
    return found
