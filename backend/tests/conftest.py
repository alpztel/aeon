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


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", default=False,
                     help="run tests marked @pytest.mark.network (they contact IRSA)")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: needs internet access to NASA/IPAC IRSA (skipped by default)")


def pytest_collection_modifyitems(config, items):
    import os

    if config.getoption("--run-network") or os.environ.get("AEON_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test: use --run-network or AEON_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
