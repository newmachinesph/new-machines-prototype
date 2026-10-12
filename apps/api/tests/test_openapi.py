import json
import re
from pathlib import Path

from app.main import create_app

COMMITTED = Path(__file__).parents[1] / "openapi.json"


def test_openapi_matches_committed_file():
    """Run `uv run python scripts/export_openapi.py` after changing routes or models."""
    assert json.loads(COMMITTED.read_text("utf-8")) == create_app().openapi()


def test_every_operation_has_an_id():
    spec = create_app().openapi()
    ops = [op for path in spec["paths"].values() for op in path.values()]
    assert all("operationId" in op for op in ops)


def operations(spec: dict) -> list[dict]:
    return [op for path in spec["paths"].values() for op in path.values()]


def test_operation_ids_are_unique():
    ids = [op["operationId"] for op in operations(create_app().openapi())]
    assert len(ids) == len(set(ids))


def test_auth_is_a_bearer_scheme_not_a_header_parameter():
    spec = create_app().openapi()
    schemes = spec["components"]["securitySchemes"]
    assert [s["scheme"] for s in schemes.values()] == ["bearer"]
    for op in operations(spec):
        assert op["security"] == [{name: []} for name in schemes]
        assert all(p["name"].lower() != "authorization" for p in op.get("parameters", []))


def test_errors_document_problem_json():
    spec = create_app().openapi()
    assert "Problem" in spec["components"]["schemas"]
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    for op in operations(spec):
        for status in ("401", "403", "404", "409", "422"):
            content = op["responses"][status]["content"]
            problem = {"schema": {"$ref": "#/components/schemas/Problem"}}
            assert content == {"application/problem+json": problem}


def test_only_request_bodies_forbid_unknown_keys():
    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]
    requests = {
        op["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
        for op in operations(spec)
        if "requestBody" in op
    }
    pending = list(requests)
    while pending:  # nested input models (a pack's connectors, a connector's defaults) are request models too
        refs = set(re.findall(r"#/components/schemas/(\w+)", json.dumps(schemas[pending.pop()])))
        pending += list(refs - requests)
        requests |= refs
    assert requests and all(schemas[name].get("additionalProperties") is False for name in requests)
    responses = set(schemas) - requests
    assert responses and all("additionalProperties" not in schemas[name] for name in responses)
