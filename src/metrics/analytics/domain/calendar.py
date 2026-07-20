"""Pure calendar logic — no DB. Equivalent to the SQL previously used in
burndown._working_days (isodow NOT IN (6, 7) + an anti-join against
team_days_off): a day counts as a working day if it's Mon-Fri and not
covered by any day-off range."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

WEEKEND_ISOWEEKDAYS = (6, 7)  # Saturday, Sunday (date.isoweekday(): Mon=1..Sun=7)


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def working_days(start: date, end: date, days_off: list[DateRange]) -> list[date]:
    if start > end:
        return []
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.isoweekday() not in WEEKEND_ISOWEEKDAYS and not any(
            r.contains(cursor) for r in days_off
        ):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days
