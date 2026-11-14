import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from aeon.main import app  # noqa: E402

CONTRACT = json.loads((BACKEND.parent / "openapi.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def contract():
    return CONTRACT


def assert_schema(payload, schema_name: str):
    """Validate a response body against a component schema of the frozen openapi.json."""
    schema = {**CONTRACT, "$ref": f"#/components/schemas/{schema_name}"}
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
