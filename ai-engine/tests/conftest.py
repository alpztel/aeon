"""Pytest fixtures and OpenAPI contract schema validator for ai-engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from app.main import app  # noqa: E402

CONTRACT_PATH = SERVICE_DIR.parent / "openapi.json"
CONTRACT: dict[str, Any] = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


def assert_path_response_schema(payload: Any, path: str, method: str = "post", status: str = "200") -> None:
    """Validate a response payload against a path's response schema in frozen openapi.json."""
    resp_schema = CONTRACT["paths"][path][method.lower()]["responses"][status]["content"]["application/json"]["schema"]
    root_schema = {**CONTRACT, **resp_schema}
    errors = sorted(Draft202012Validator(root_schema).iter_errors(payload), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])
