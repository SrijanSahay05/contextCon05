import importlib
import pkgutil
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.schemas as app_schemas
from app.main import app

client = TestClient(app)
SPEC: dict[str, Any] = app.openapi()
INVESTOR = {"X-Investor-Id": "3f2b8c1e-6a4d-4e2f-9b1a-7c5d2e8f0a11"}
ANY_ID = "f1e2d3c4-b5a6-4978-8a6b-5c4d3e2f1a01"

# The 0B route table (paths use the OpenAPI parameter names).
ROUTES = {
    ("post", "/investors/onboard"),
    ("post", "/investors/{investor_id}/confirm-identity"),
    ("get", "/investors/{investor_id}"),
    ("get", "/funds/{fund_id}/alias-candidates"),
    ("post", "/funds/{fund_id}/aliases"),
    ("get", "/theses/{thesis_id}"),
    ("put", "/theses/{thesis_id}"),
    ("post", "/theses/{thesis_id}/confirm"),
    ("get", "/scoring-profiles/{profile_id}"),
    ("put", "/scoring-profiles/{profile_id}"),
    ("post", "/scoring-profiles/{profile_id}/confirm"),
    ("post", "/searches"),
    ("get", "/searches"),
    ("get", "/searches/{search_id}"),
    ("put", "/searches/{search_id}/filters"),
    ("post", "/searches/{search_id}/run"),
    ("get", "/candidates/{candidate_id}"),
    ("post", "/candidates/{candidate_id}/status"),
    ("post", "/candidates/{candidate_id}/rescore"),
    ("post", "/candidates/{candidate_id}/recheck"),
    ("post", "/candidates/{candidate_id}/outreach"),
    ("put", "/outreach/{outreach_id}"),
    ("post", "/outreach/{outreach_id}/approve"),
    ("post", "/outreach/{outreach_id}/send"),
    ("post", "/outreach/{outreach_id}/mark-sent"),
    ("post", "/candidates/{candidate_id}/memo"),
    ("get", "/memos/{memo_id}"),
    ("post", "/candidates/{candidate_id}/dd"),
    ("get", "/candidates/{candidate_id}/dd"),
    ("post", "/dd/{request_id}/approve"),
    ("post", "/dd/{request_id}/send"),
    ("post", "/dd/{request_id}/mark-sent"),
    ("post", "/candidates/{candidate_id}/documents"),
    ("get", "/sources/{source_id}"),
    ("get", "/runs/{run_id}"),
    ("get", "/runs/{run_id}/events"),
    ("get", "/watch-events"),
    ("post", "/watch-events/{event_id}/dismiss"),
    ("post", "/webhooks/crustdata/watch"),
    ("get", "/integrations/gmail/connect"),
    ("get", "/integrations/gmail/callback"),
    ("delete", "/integrations/gmail"),
    ("get", "/integrations/gmail"),
    ("get", "/healthz"),
}
PUBLIC = {
    ("post", "/investors/onboard"),
    ("get", "/healthz"),
    ("post", "/webhooks/crustdata/watch"),
    ("get", "/integrations/gmail/callback"),
}


def _spec_routes() -> set[tuple[str, str]]:
    return {(m, p) for p, ops in SPEC["paths"].items() for m in ops}


def test_every_route_is_in_the_spec() -> None:
    assert _spec_routes() == ROUTES


def test_every_model_has_an_example() -> None:
    missing = [
        name for name, schema in SPEC["components"]["schemas"].items()
        if "properties" in schema and not name.startswith("Body_") and "examples" not in schema
    ]
    assert missing == []


def test_investor_header_required_exactly_where_expected() -> None:
    for method, path in ROUTES:
        op = SPEC["paths"][path][method]
        has_auth = any("APIKeyHeader" in s for s in op.get("security", []))
        assert has_auth == ((method, path) not in PUBLIC), (method, path)


def test_stub_returns_501_envelope() -> None:
    # an endpoint that is still a stub (candidate detail is implemented now)
    response = client.post(f"/candidates/{ANY_ID}/recheck", headers=INVESTOR)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"
    assert set(response.json()["error"]) == {"code", "message", "details"}


def test_public_stub_needs_no_header() -> None:
    # a public route that is still a stub (onboard is implemented and would call Crustdata)
    response = client.post("/webhooks/crustdata/watch?token=t", json={"event": "test"})

    assert response.status_code == 501


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [({}, 401, "not_allowed"), ({"X-Investor-Id": "nope"}, 422, "validation_error")],
)
def test_missing_or_bad_investor_header(headers: dict[str, str], status: int, code: str) -> None:
    response = client.get(f"/candidates/{ANY_ID}", headers=headers)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_validation_error_uses_envelope() -> None:
    response = client.post("/investors/onboard", json={"name": "only a name"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["errors"]


def test_unknown_route_uses_envelope() -> None:
    response = client.get("/no-such-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_healthz_still_works() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_examples_are_valid_models() -> None:
    checked = 0
    for info in pkgutil.iter_modules(app_schemas.__path__):
        module = importlib.import_module(f"app.schemas.{info.name}")
        for obj in vars(module).values():
            if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                continue
            if obj.__module__ != module.__name__:
                continue
            extra = obj.model_config.get("json_schema_extra")
            assert isinstance(extra, dict), obj.__name__
            items = extra["examples"]
            assert isinstance(items, list), obj.__name__
            for example in items:
                obj.model_validate(example)
                checked += 1
    assert checked > 40


def test_upload_is_multipart() -> None:
    response = client.post(
        f"/candidates/{ANY_ID}/documents",
        headers=INVESTOR,
        files={"file": ("deck.pdf", b"%PDF-1.4", "application/pdf")},
        data={"kind": "deck"},
    )

    assert response.status_code == 501
