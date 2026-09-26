"""Clause segmentation, scoring, and the compile pipeline."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import date
from decimal import Decimal

from glasswing_domain.ids import uuid7
from glasswing_domain.money import Money
from glasswing_domain.ontology import Clause, Eligibility, Period
from glasswing_domain.prompts import prompt_sha256
from glasswing_domain.rules import Obligation, RuleIR, Threshold

# Matches "8.2 Rebate" / "12. Governing Law" style numbering (Meridian
# samples, the acme golden test) OR "ARTICLE 3 - Repayment" style numbering
# (common in real SEC EDGAR exhibits). Alternation, not two passes, so a
# document can't accidentally match both and double-count a line.
HEADING = re.compile(
    r"(?mi)^\s*(?:ARTICLE\s+(?P<article_num>\d+)\s*[-.:]?\s*(?P<article_heading>[^\n]*)"
    r"|(?P<section>\d+(?:\.\d+)*)\.?\s+(?P<heading>[^\n]+))$"
)
BOILERPLATE = ("governing law", "entire agreement", "whereas", "counterparts", "notices.")

_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")


def strip_markup(text: str) -> str:
    """Strip SGML/HTML wrappers (raw SEC EDGAR exhibits ship as <DOCUMENT>/
    <TYPE>/<TEXT>-tagged HTML, not plain text). A no-op on already-clean text."""
    if "<" not in text:
        return text
    cleaned = _TAG_RE.sub(" ", text)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n", cleaned)
    return cleaned


def parse_blocks(text: str) -> list[tuple[str, str, str]]:
    """Return (section, heading, body) for numbered/ARTICLE-numbered clauses.
    Preamble is section 0.

    Many contracts (bilingual SEC filings especially) repeat the entire
    document in a second language after the original — once an ARTICLE
    number repeats, everything after that point is a duplicate translation,
    not new content, so parsing stops there.
    """
    matches = list(HEADING.finditer(text))
    blocks: list[tuple[str, str, str]] = []
    if not matches:
        blocks.append(("0", "Preamble", text.strip()))
        return blocks
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            blocks.append(("0", "Preamble", preamble))

    seen_article_numbers: set[int] = set()
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()

        if match.group("article_num"):
            number = int(match.group("article_num"))
            if number in seen_article_numbers:
                break
            seen_article_numbers.add(number)
            section = str(number)
            heading = (match.group("article_heading") or "").strip()
        else:
            section = match.group("section")
            heading = match.group("heading").strip()

        blocks.append((section, heading, body))
    return blocks


def segment_clauses(text: str) -> list[Clause]:
    text = strip_markup(text)
    clauses: list[Clause] = []
    for section, heading, body in parse_blocks(text):
        full = body if section == "0" else f"{heading}\n{body}".strip()
        clauses.append(
            Clause(
                clause_id=section,
                section=section,
                heading=heading,
                text=full,
                page=1,
                bbox=[0.0, float(len(clauses)) * 12.0, 400.0, 12.0],
            )
        )
    return clauses


def hash_embed(text: str, dimensions: int = 16) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append((byte / 255.0) * 2 - 1)
            if len(values) == dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def is_boilerplate(clause: Clause) -> bool:
    lowered = clause.text.lower()
    if clause.section == "0":
        return True
    return any(token in lowered for token in BOILERPLATE)


def _money_phrase(text: str) -> Decimal | None:
    match = re.search(r"\$\s*([0-9][0-9,]*(?:\.\d+)?)\s*(million|billion)?", text, re.I)
    if not match:
        return None
    number = Decimal(match.group(1).replace(",", ""))
    unit = (match.group(2) or "").lower()
    if unit == "million":
        number *= Decimal("1000000")
    elif unit == "billion":
        number *= Decimal("1000000000")
    return number


def _percent(text: str) -> Decimal | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        return None
    return Decimal(match.group(1)) / Decimal("100")


def compile_clause_deterministic(clause: Clause, supplier_key: str) -> RuleIR | None:
    """Pattern compiler used by FakeLlm so the pipeline still goes through the LlmClient."""
    text = clause.text
    lowered = text.lower()
    if "rebate" in lowered and "exceeding" in lowered:
        rate = _percent(text) or Decimal("0")
        threshold = _money_phrase(text) or Decimal("0")
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="condition",
            rule_type="threshold_rebate",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["invoice.posted", "spend.adjusted"],
            assertion="rebated_amount_matches_obligation",
            severity="high",
            needs_confirmation=["application"],
            period=Period(type="contract_year", anchor="effective_date"),
            eligibility=Eligibility(include_categories=["goods"], exclude=["freight", "tax"]),
            threshold=Threshold(metric="eligible_spend", op="gte", amount=threshold, currency="USD"),
            obligation=Obligation(rate=rate, application=None),
            value_amount=Money(amount=threshold, currency="USD"),
        )
    price = re.search(r"(?im)^(.+?)\s+unit price is\s+\$([0-9]+(?:\.[0-9]+)?)", text)
    if price:
        sku = price.group(1).strip()
        if sku.lower().startswith("the "):
            sku = sku[4:]
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="condition",
            rule_type="price_match",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["invoice.posted"],
            assertion="unit_price_at_or_below_contract",
            sku=sku,
            contracted_price=Money(amount=Decimal(price.group(2)), currency="USD"),
            value_amount=Money(amount=Decimal(price.group(2)), currency="USD"),
        )
    if "commercially reasonable" in lowered or "reasonable efforts" in lowered:
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="natural_language",
            rule_type="natural_language",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["performance.reported"],
            clause_text=clause.text,
            decision_prompt="Did the supplier fail to prioritize the buyer during a shortage?",
            severity="medium",
        )
    if "net" in lowered and "discount" in lowered or re.search(r"\d+%\s+\d+\s+days?\s+net", lowered):
        perc = _percent(text) or Decimal("0")
        days = re.search(r"(\d+)\s+days?\s+net\s+(\d+)", lowered)
        discount_days = int(days.group(1)) if days else 10
        net_days = int(days.group(2)) if days else 30
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="condition",
            rule_type="payment_terms",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["invoice.posted"],
            discount_percent=perc,
            discount_days=discount_days,
            net_days=net_days,
        )
    if "notice" in lowered and "expir" in lowered:
        notice = re.search(r"(\d+)\s+days", lowered)
        expiry = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="condition",
            rule_type="renewal_notice",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["clock.tick"],
            notice_days=int(notice.group(1)) if notice else 30,
            expiry=date.fromisoformat(expiry.group(1)) if expiry else None,
            needs_confirmation=[] if expiry else ["expiry"],
        )
    if "delivery rate" in lowered or "penalty" in lowered and "%" in text and "target" not in lowered:
        if "delivery" in lowered or "sla" in lowered or "service level" in lowered:
            percents = re.findall(r"(\d+(?:\.\d+)?)\s*%", text)
            target = Decimal(percents[0]) / Decimal("100") if percents else Decimal("0.98")
            penalty = Decimal(percents[1]) / Decimal("100") if len(percents) > 1 else Decimal("0.01")
            return RuleIR(
                rule_id=f"rule-{clause.clause_id}",
                kind="condition",
                rule_type="sla_penalty",
                supplier_key=supplier_key,
                source_clause_ids=[clause.clause_id],
                trigger=["performance.reported"],
                metric="delivery_rate",
                target=target,
                penalty_rate=penalty,
                severity="high",
            )
    if "discount" in lowered and "unit" in lowered:
        tiers = re.findall(r"(\d+(?:\.\d+)?)\s*%\s+discount\s+at\s+([0-9,]+)\s+units", lowered)
        if tiers:
            from glasswing_domain.ontology import DiscountTier

            parsed = [
                DiscountTier(min_qty=Decimal(qty.replace(",", "")), discount_rate=Decimal(rate) / Decimal("100"))
                for rate, qty in tiers
            ]
            list_price = _money_phrase(text) or Decimal("10")
            sku_match = re.search(r"for\s+([A-Za-z0-9 -]+?),", text)
            return RuleIR(
                rule_id=f"rule-{clause.clause_id}",
                kind="condition",
                rule_type="volume_discount",
                supplier_key=supplier_key,
                source_clause_ids=[clause.clause_id],
                trigger=["invoice.posted"],
                sku=sku_match.group(1).strip() if sku_match else None,
                contracted_price=Money(amount=list_price, currency="USD"),
                tiers=parsed,
            )
    if "penalty" in lowered or "terminat" in lowered or "liability" in lowered or "most favored" in lowered or "most-favoured" in lowered or "unilateral" in lowered:
        return RuleIR(
            rule_id=f"rule-{clause.clause_id}",
            kind="natural_language",
            rule_type="natural_language",
            supplier_key=supplier_key,
            source_clause_ids=[clause.clause_id],
            trigger=["invoice.posted"],
            clause_text=clause.text,
            decision_prompt="Does this transaction breach the clause?",
            severity="high",
        )
    return None


HIGH_RISK_PHRASES = (
    "penalty",
    "termination",
    "terminate",
    "liability",
    "audit right",
    "most favored",
    "most-favoured",
    "most favoured",
    "unilateral",
)


def score_rule(rule: RuleIR, clause_text: str, high_value_threshold: Decimal) -> RuleIR:
    reasons: list[str] = []
    value_band = "unknown"
    amount = None
    if rule.threshold is not None:
        amount = rule.threshold.amount
    elif rule.value_amount is not None:
        amount = rule.value_amount.amount
    elif rule.contracted_price is not None and rule.rule_type != "price_match":
        amount = rule.contracted_price.amount
    if amount is None:
        value_band = "unknown"
    elif amount >= high_value_threshold:
        value_band = "high"
        reasons.append(f"value {amount} meets the high-value threshold {high_value_threshold}")
    else:
        value_band = "low"
    risk = "low"
    lowered = clause_text.lower()
    if rule.kind == "natural_language" or rule.rule_type == "natural_language":
        risk = "high"
        reasons.append("clause stays in natural language")
    if rule.needs_confirmation:
        risk = "high"
        reasons.append("fields still need confirmation: " + ", ".join(rule.needs_confirmation))
    for phrase in HIGH_RISK_PHRASES:
        if phrase in lowered:
            risk = "high"
            reasons.append(f"clause language includes '{phrase}'")
            break
    value_amount = Money(amount=amount, currency="USD") if amount is not None else None
    return rule.model_copy(
        update={
            "value_band": value_band,
            "risk_band": risk,
            "warning_reasons": reasons,
            "value_amount": value_amount,
        }
    )


def document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compiler_prompt_hash() -> str:
    return prompt_sha256("compiler_system.txt")


def new_rule_id() -> str:
    return f"rule-{uuid7()}"
