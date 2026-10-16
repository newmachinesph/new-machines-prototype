"""Sub-project D, part 2: the publishing routes and fields are in the contract, and every route is live
only."""

import pytest

from app.main import create_app

ORG = "/v1/organizations/{org_id}"
EXPECTED = {
    ("get", f"{ORG}/publisher"): "getPublisher",
    ("put", f"{ORG}/publisher"): "savePublisher",
    ("delete", f"{ORG}/publisher"): "disablePublisher",
    ("post", f"{ORG}/studio/agents/{{key}}/submissions"): "submitStudioAgent",
    ("post", f"{ORG}/studio/packs/{{key}}/submissions"): "submitStudioPack",
    ("get", f"{ORG}/studio/listings"): "listStudioListings",
    ("get", f"{ORG}/studio/listings/{{listing_id}}"): "getStudioListing",
    ("get", f"{ORG}/studio/earnings"): "getStudioEarnings",
    ("post", f"{ORG}/agent-installations/{{slug}}:upgrade"): "upgradeWorkflowPack",
    ("get", "/v1/ops/listings"): "opsListListings",
    ("get", "/v1/ops/listings/{listing_id}"): "opsGetListing",
    ("post", "/v1/ops/listings/{listing_id}:approve"): "opsApproveListing",
    ("post", "/v1/ops/listings/{listing_id}:request-changes"): "opsRequestListingChanges",
    ("post", "/v1/ops/listings/{listing_id}:reject"): "opsRejectListing",
    ("post", "/v1/ops/listings/{listing_id}:unlist"): "opsUnlistListing",
    ("post", "/v1/ops/listings/{listing_id}:relist"): "opsRelistListing",
}
FIELDS = {
    "Pack": "listing",
    "Agent": "listing",
    "PaletteAgent": "listing",
    "Receipt": "fees",
    "LedgerTxn": "fees",
    "OpsOverview": "listingsInReview",
}


def test_the_publishing_operations_are_in_the_contract():
    spec = create_app().openapi()
    found = {(m, p): op["operationId"] for p, ops in spec["paths"].items() for m, op in ops.items()}
    assert {k: found.get(k) for k in EXPECTED} == EXPECTED


def test_the_publishing_reads_declare_the_manager_403():
    spec = create_app().openapi()
    ops = {op["operationId"]: op for ops in spec["paths"].values() for op in ops.values()}
    for op_id in ("getPublisher", "listStudioListings", "getStudioListing", "getStudioEarnings"):
        assert "POLICY_DENIED" in ops[op_id]["responses"]["403"]["description"], op_id


def test_the_marketplace_reads_gain_their_publishing_fields():
    schemas = create_app().openapi()["components"]["schemas"]
    for model, field in FIELDS.items():
        assert field in schemas[model]["properties"], model
    assert "publisherEarningsMonth" in schemas["OpsOverview"]["properties"]


DEMO = "/v1/organizations/org_hp01"
LISTING = "lst_000000000000"
REASON = {"reason": "Checked"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", f"{DEMO}/publisher", None),
        ("PUT", f"{DEMO}/publisher", {"name": "Acme Labs"}),
        ("DELETE", f"{DEMO}/publisher", None),
        ("POST", f"{DEMO}/studio/agents/org-x--a/submissions", {"priceMinor": 0}),
        ("POST", f"{DEMO}/studio/packs/org-x--p/submissions", {"priceMinor": 0}),
        ("GET", f"{DEMO}/studio/listings", None),
        ("GET", f"{DEMO}/studio/listings/{LISTING}", None),
        ("GET", f"{DEMO}/studio/earnings", None),
        ("POST", f"{DEMO}/agent-installations/order-payment-reconciliation:upgrade", None),
        ("GET", "/v1/ops/listings", None),
        ("GET", f"/v1/ops/listings/{LISTING}", None),
        ("POST", f"/v1/ops/listings/{LISTING}:approve", REASON),
        ("POST", f"/v1/ops/listings/{LISTING}:unlist", REASON),
    ],
)
def test_every_publishing_route_is_live_only(client, method, path, body):
    res = client.request(method, path, json=body)
    assert res.status_code == 404, res.text
    assert res.json()["code"] == "NOT_FOUND"
