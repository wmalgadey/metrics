import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "azdo"


@pytest.fixture
def load_fixture():
    def _load(name: str):
        with (FIXTURES / name).open("r", encoding="utf-8") as fh:
            return json.load(fh)

    return _load
