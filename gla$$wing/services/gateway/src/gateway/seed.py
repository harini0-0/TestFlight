"""Load the Acme contract, approve the engine, and post the invoice that leaks $4,200."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from glasswing_domain.money import Money
from glasswing_domain.transactions import Invoice, InvoiceLine
from sqlalchemy.orm import Session

from gateway.platform import Platform

ACME = """MASTER SUPPLY AGREEMENT
Supplier: Acme

8.2 Rebate
Supplier will provide a 5% rebate on annual purchases exceeding $2 million, calculated on aggregate eligible purchases during the contract year.

8.3 Price
Widget A unit price is $10.00.

9.1 Efforts
Supplier will use commercially reasonable efforts to prioritize the buyer's orders during a shortage.

12. Governing Law
This agreement is governed by the laws of Delaware.
"""


def _invoice(number: str, amount: str, rebate: str) -> Invoice:
    quantity = Decimal(amount) / Decimal("10")
    return Invoice(
        transaction_id=number,
        supplier_key="acme",
        invoice_number=number,
        invoice_date=date(2026, 4, 1),
        lines=[
            InvoiceLine(
                sku="Widget A",
                description="Widget A",
                category="goods",
                quantity=quantity,
                unit_price=Money(amount=Decimal("10"), currency="USD"),
                extended_amount=Money(amount=Decimal(amount), currency="USD"),
                rebate_amount=Money(amount=Decimal(rebate), currency="USD"),
            )
        ],
    )


def seed_tenant(session: Session, tenant_id: str = "demo") -> dict:
    platform = Platform(session)
    document = platform.store_contract(tenant_id, "acme.txt", "text/plain", ACME, "seed://acme", date(2026, 1, 1))
    bundle = platform.compile(tenant_id, document.id, "seed")
    rebate = next(rule for rule in platform._rules(bundle) if rule.rule_type == "threshold_rebate")
    platform.resolve_field(
        tenant_id,
        bundle.id,
        rebate.rule_id,
        "application",
        "rate_on_each_invoice_once_crossed",
    )
    report = platform.run_tests(tenant_id, bundle.id)
    platform.approve(tenant_id, bundle.id, "seed", {rebate.rule_id: False}, {})
    platform.accept_event(tenant_id, _invoice("PRIOR", "2316000", "115800"), "seed-prior")
    leaked = platform.accept_event(tenant_id, _invoice("INV-29381", "84000", "0"), "seed-leak")
    return {
        "document_id": document.id,
        "bundle_id": bundle.id,
        "tests": len(report["results"]),
        "evaluations": leaked["evaluations"],
    }
