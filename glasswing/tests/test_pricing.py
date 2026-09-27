"""Appendix C unit prices, including the footer that names both publishers."""

import json
from decimal import Decimal
from pathlib import Path

from compiler.pricing import judge_dir_price
from glasswing_adapters.runtime import LocalPdfParser
from ingestion.local_invoice import invoices_from_text

_CLAUSE = (
    "Office Professional/Standard Level D less 7.5 percent. "
    "The customer discount is 16.50 percent. "
    "The administrative fee is 0.75 percent of the customer price."
)


def test_office_line_is_not_treated_as_adobe_because_the_footer_says_adobe():
    description = (
        "Office Professional Plus. Level D price 435.00. "
        "STATE OF TEXAS DIR ADOBE AND MICROSOFT SOFTWARE"
    )
    judged = judge_dir_price(
        "1.5.1",
        _CLAUSE,
        {
            "lines": [
                {
                    "sku": "269-05704",
                    "description": description,
                    "quantity": "850",
                    "unit_price": {"amount": "365.95", "currency": "USD"},
                }
            ]
        },
    )
    assert judged is not None
    assert judged["outcome"] == "violation"
    assert Decimal(judged["estimated_amount"]) == Decimal("23332.50")


def test_williamson_invoice_shows_the_planted_overcharge():
    pdf = Path("RealTest/03-stage4-invoice/Insight-Invoice-0229611840-Williamson-County-DIR-CPO-5239.pdf").read_bytes()
    text = LocalPdfParser().extract_text(pdf, "invoice.pdf")
    event = invoices_from_text(text, "insight")[0]
    judged = judge_dir_price("1.5.1", _CLAUSE, json.loads(event.model_dump_json()))
    assert judged is not None
    assert judged["outcome"] == "violation"
    assert Decimal(judged["estimated_amount"]) == Decimal("41191.00")
