import json
from pathlib import Path

import pytest

GOLDEN = Path(__file__).resolve().parents[2] / "golden"


def load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


def plain(v):
    """The JSON form the golden capture wrote (tuples become lists; -0.0 compares equal to 0)."""
    return json.loads(json.dumps(v))


@pytest.fixture(scope="session")
def copilot_golden() -> dict:
    return load("copilot.json")


@pytest.fixture(scope="session")
def replan_golden() -> dict:
    return load("replan.json")


@pytest.fixture(scope="session")
def evaluation_golden() -> dict:
    return load("evaluation.json")
