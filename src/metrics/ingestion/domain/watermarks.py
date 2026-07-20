"""Pure date-arithmetic helpers for incremental sync — kept separate from I/O for testability."""

from __future__ import annotations

from datetime import date, datetime, timedelta


def parse_watermark_date(watermark: str | None) -> date | None:
    if not watermark:
        return None
    return datetime.fromisoformat(watermark.replace("Z", "+00:00")).date()


def snapshot_date_range(
    start_date: date, end_date: date, watermark: date | None, today: date
) -> tuple[date, date]:
    """Range to fetch WorkItemSnapshot for: from the day after the last watermark
    (or the sprint start on a first/full sync) through today or the sprint end,
    whichever is earlier."""
    date_from = watermark + timedelta(days=1) if watermark else start_date
    date_to = min(end_date, today)
    if date_from > date_to:
        date_from = date_to
    return date_from, date_to


def is_frozen(timeframe: str | None, end_date: date | None, today: date, grace_days: int) -> bool:
    """A completed sprint is frozen (skipped by default) once the grace period
    after its end date has elapsed."""
    if timeframe != "past" or end_date is None:
        return False
    return today > end_date + timedelta(days=grace_days)
