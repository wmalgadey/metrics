"""State classification — pure, no DB. Moved from the former storage/loaders.py."""

from __future__ import annotations

from ...config import StatesConfig


def classify_state(state: str, state_category: str, states: StatesConfig) -> str:
    """Config-adjusted classification, falling back to Analytics' own StateCategory."""
    if state in states.removed:
        return "Removed"
    if state in states.done:
        return "Completed"
    if state in states.in_progress:
        return "InProgress"
    return state_category or "Other"
