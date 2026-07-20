"""Shared fixtures for BDD scenarios."""

from __future__ import annotations

import duckdb
import pytest

from metrics.config import StatesConfig
from metrics.storage.db import apply_schema

DEFAULT_STATES = StatesConfig(
    done=["Done", "Closed"],
    in_progress=["Committed", "In Progress"],
    removed=["Removed"],
)


@pytest.fixture
def bdd_context():
    """A plain dict steps use to pass state to each other within one scenario."""
    return {}


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    apply_schema(c)
    yield c
    c.close()


@pytest.fixture
def states():
    return DEFAULT_STATES
