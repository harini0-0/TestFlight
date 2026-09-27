from datetime import date
from decimal import Decimal

from actions.machine import Action, approve, execute, propose
from audit.chain import AuditLog
from control_engine.evaluators import (
    evaluate_payment_terms,
    evaluate_renewal_notice,
    evaluate_sla,
    evaluate_volume_discount,
)
from glasswing_domain.events import AuditEvent
from glasswing_domain.money import Money
from glasswing_domain.ontology import DiscountTier
from glasswing_domain.rules import RuleIR
from glasswing_domain.transactions import ClockTick, Invoice, InvoiceLine, PerformanceEvent


def test_audit_chain_verifies_and_has_no_mutation_api():
    log = AuditLog()
    first = log.append(AuditEvent(tenant_id="t", actor="a", action="one", object_refs=["1"], correlation_id="c1", payload={}))
    second = log.append(AuditEvent(tenant_id="t", actor="a", action="two", object_refs=["2"], correlation_id="c2", payload={"n": 1}))
    assert first.prev_hash == "0" * 64
    assert second.prev_hash == first.row_hash
    assert log.verify()
    assert not hasattr(log, "update")
    assert not hasattr(log, "delete")


def test_high_risk_action_requires_a_different_approver_and_write_scope():
    action = propose(
        Action(
            action_id="a1",
            tenant_id="t",
            finding_id="f1",
            action_type="erp_adjustment",
            status="draft",
            requester="analyst",
            risk="high",
            sod_required=True,
            connector_write_scope=False,
        ),
        "open",
    )
    denied = approve(action, "analyst")
    assert denied.failure_reason
    blocked = approve(action, "manager")
    assert "write scope" in (blocked.failure_reason or "")
    action.connector_write_scope = True
    allowed = approve(action, "manager")
    assert allowed.status == "approved"
    done = execute(allowed)
    assert done.status == "succeeded"
    assert done.dry_run_diff["applied"] is False


def test_other_rule_types():
    price = Money(amount=Decimal("10"), currency="USD")
    volume = RuleIR(
        rule_id="vol",
        kind="condition",
        rule_type="volume_discount",
        supplier_key="acme",
        source_clause_ids=["4"],
        trigger=["invoice.posted"],
        sku="Bolt",
        contracted_price=price,
        tiers=[DiscountTier(min_qty=Decimal("1000"), discount_rate=Decimal("0.10"))],
    )
    invoice = Invoice(
        transaction_id="v",
        supplier_key="acme",
        invoice_number="v",
        invoice_date=date(2026, 1, 1),
        lines=[
            InvoiceLine(
                sku="Bolt",
                quantity=Decimal("1000"),
                unit_price=Money(amount=Decimal("10"), currency="USD"),
                extended_amount=Money(amount=Decimal("10000"), currency="USD"),
            )
        ],
    )
    assert evaluate_volume_discount(volume, invoice).outcome == "violation"
    payment = RuleIR(
        rule_id="pay",
        kind="condition",
        rule_type="payment_terms",
        supplier_key="acme",
        source_clause_ids=["5"],
        trigger=["invoice.posted"],
        discount_percent=Decimal("0.02"),
        discount_days=10,
        net_days=30,
    )
    paid = invoice.model_copy(update={"paid_date": date(2026, 1, 5), "discount_taken": Money(amount=Decimal("0"), currency="USD")})
    missed = evaluate_payment_terms(payment, paid)
    assert missed.outcome == "violation"
    assert missed.amount_at_risk is not None
    assert missed.amount_at_risk.amount == Decimal("200.0000")
    renewal = RuleIR(
        rule_id="ren",
        kind="condition",
        rule_type="renewal_notice",
        supplier_key="acme",
        source_clause_ids=["6"],
        trigger=["clock.tick"],
        notice_days=30,
        expiry=date(2026, 12, 31),
    )
    tick = ClockTick(transaction_id="t", supplier_key="acme", as_of=date(2026, 12, 15), notice_recorded=False)
    assert evaluate_renewal_notice(renewal, tick).outcome == "violation"
    sla = RuleIR(
        rule_id="sla",
        kind="condition",
        rule_type="sla_penalty",
        supplier_key="acme",
        source_clause_ids=["7"],
        trigger=["performance.reported"],
        metric="delivery_rate",
        target=Decimal("0.98"),
        penalty_rate=Decimal("0.01"),
    )
    event = PerformanceEvent(
        transaction_id="p",
        supplier_key="acme",
        metric="delivery_rate",
        value=Decimal("0.90"),
        period_spend=Money(amount=Decimal("1000"), currency="USD"),
        reported_on=date(2026, 6, 1),
    )
    penalty = evaluate_sla(sla, event)
    assert penalty.outcome == "violation"
    assert penalty.amount_at_risk is not None
    assert penalty.amount_at_risk.amount == Decimal("10.0000")
