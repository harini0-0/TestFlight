"""Contract-year and calendar-year period keys. Never guessed at evaluation time."""

from __future__ import annotations

from datetime import date

from glasswing_domain.ontology import Period


def period_key(period: Period, as_of: date, effective: date) -> str:
    if period.type == "calendar_year" or period.anchor == "calendar":
        return f"calendar:{as_of.year}"
    start_year = as_of.year
    anniversary = date(as_of.year, effective.month, effective.day) if _valid(as_of.year, effective) else date(as_of.year, effective.month, 28)
    if as_of < anniversary:
        start_year -= 1
    start = date(start_year, effective.month, effective.day) if _valid(start_year, effective) else date(start_year, effective.month, 28)
    return f"contract:{start.isoformat()}"


def _valid(year: int, effective: date) -> bool:
    try:
        date(year, effective.month, effective.day)
    except ValueError:
        return False
    return True
