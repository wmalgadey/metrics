"""The burndown ideal line — pure, no DB. Moved verbatim from the former
metrics.metrics.burndown._ideal_line."""

from __future__ import annotations

from datetime import date, timedelta


def ideal_line(
    day1: date, sprint_end: date, working_days: list[date], day1_scope: int
) -> dict[date, float]:
    """Linear ideal: day1_scope on day1, 0 on the last working day, flat over
    weekends/days off in between."""
    ideal: dict[date, float] = {}
    n = len(working_days)
    last_value = float(day1_scope)
    cursor = day1
    working_idx = 0
    while cursor <= sprint_end:
        if working_idx < n and working_days[working_idx] == cursor:
            if n > 1:
                last_value = day1_scope * (1 - working_idx / (n - 1))
            else:
                last_value = 0.0
            working_idx += 1
        ideal[cursor] = last_value
        cursor += timedelta(days=1)
    return ideal
