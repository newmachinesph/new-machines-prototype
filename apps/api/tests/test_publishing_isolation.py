"""Sub-project D, cross-workspace isolation: Ben's workspace never reaches Ana's publisher settings,
submissions, listings or earnings, and never sees a version of her pack or agent that ops has not approved,
by any path (marketplace list and detail, install, update, run start, connections, the agent catalog, the
Studio palette and build context). Ops decisions are for ops admins only; support reads."""

from collections.abc import Callable

import pytest

from app import studio
from app.defs import owners, registry
from app.defs.model import Definition, path_for
from tests.publishing_seed import add_listing, add_publisher, add_version, approve_and_list, defs_of
from tests.team_seed import TEAM_AGENT, clone_pack, invoice_nudges
from tests.test_live_catalog import INPUT, As
from tests.test_ops_state import OPS, OPS_EMAIL, ana, live, ops_post, starts  # noqa: F401

PACK = "order-payment-reconciliation"
APPS = ("shopify", "stripe", "googlesheets")
PACK_V1, PACK_V2 = "Acme recon", "Acme recon two"
AGENT_V1, AGENT_V2 = TEAM_AGENT.name, "Invoice helper two"
NEVER_APPROVED = ("checking", "in_review", "checks_failed", "changes_requested", "rejected")
NEWER = ("newer_in_review", "newer_changes_requested", "newer_rejected")
STATES = (*NEVER_APPROVED, "unlisted", *NEWER)
DECISIONS = ("approve", "request-changes", "reject", "unlist", "relist")


@pytest.fixture
def ben(live) -> As:  # noqa: F811
    return As(live, "ben")


def _rows(db, query: str, *args) -> list[dict]:
    db.commit()
    return db.execute(query, args).fetchall()


def _republish(db, kind: str, key: str, name: str) -> None:
    v = registry.latest(db, kind, key)
    d = Definition(
        kind=kind, key=key, body={**v.body, "name": name}, files=dict(v.files), path=path_for(kind, key)
    )
    registry.publish(db, d, "test", "a newer version", source=registry.BUILDER)


def _stage(api, db, kind: str, key: str, org_id: str, state: str, refs, newer_name: str, added=None) -> str:
    """Ana's listing of `key` in `state`. A listing that was approved once lists version 1 first (and `added`
    runs then: Ben adds it while it is listed); `unlisted` is then withdrawn by ops, and a `newer_*` state
    renames the definition to `newer_name` and submits it as version 2 in that state."""
    listing = add_listing(db, kind, key, org_id, name=f"{kind} v1")
    if state in NEVER_APPROVED:
        add_version(db, listing, 1, refs(), status=state, price_minor=100)
        db.commit()
        return listing
    approve_and_list(db, listing, add_version(db, listing, 1, refs(), price_minor=100))
    db.commit()
    if added is not None:
        added()
    if state == "unlisted":
        assert (
            ops_post(api, f"/v1/ops/listings/{listing}:unlist", reason="Reported broken").status_code == 200
        )
        return listing
    _republish(db, kind, key, newer_name)
    add_version(db, listing, 2, refs(), status=state.removeprefix("newer_"), price_minor=999)
    db.commit()
    return listing


def _bens(db, org_id: str) -> dict:
    """Everything Ben's workspace has written that a refused path must not add to."""
    return {
        "installations": _rows(
            db,
            "SELECT pack_slug, pack_version, listing_version_id, cap_minor FROM installations "
            "WHERE org_id = %s ORDER BY pack_slug",
            org_id,
        ),
        "runs": _rows(db, "SELECT id FROM runs WHERE org_id = %s ORDER BY id", org_id),
        "fees": _rows(db, "SELECT id FROM fee_lines WHERE buyer_org_id = %s ORDER BY id", org_id),
    }


# --- packs ------------------------------------------------------------------------------------------------
# Three guards, one test each, so each refusal below has only its guard to answer for it:
# - never approved: another workspace's bundle holds only listed definitions (`listed_definitions`), so the
#   pack is NOT_FOUND to Ben on every path; without the guard he could add it (201) and update or start it
#   (409 PACK_NOT_HIRED).
# - a newer version in review or refused: Ben holds v1 (its installation's listing version), so every path
#   answers with v1 and its price; without the guard he would see, update to, run or pay for v2.
# - withdrawn: an unlisted pack leaves `listed_definitions`, so Ben's run of it is refused.

V1_START_FORM = ["since", "until", "spreadsheet_id"]


def _pack(db, org_id: str) -> tuple[str, Callable[[], list[dict]]]:
    add_publisher(db, org_id, "Acme Labs")
    key = clone_pack(db, PACK, org_id, "recon", title=PACK_V1)
    db.commit()
    return key, lambda: defs_of(db, [("pack", key), ("workflow", key), ("contract", key)])


def _add(ben: As, key: str) -> None:
    hire = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    res = ben.post(f"/v1/organizations/{ben.org_id}/agent-installations", json=hire)
    assert res.status_code == 201, res.text
    for app in APPS:
        assert ben.connect(app).status_code == 200


def _code(res) -> tuple[int, str]:
    return res.status_code, res.json().get("code")


@pytest.mark.parametrize("state", NEVER_APPROVED)
def test_a_pack_never_approved_is_not_found_on_every_path(live, ana, ben, starts, db, state):  # noqa: F811
    key, refs = _pack(db, ana.org_id)
    listing = add_listing(db, "pack", key, ana.org_id, name=PACK_V1)
    add_version(db, listing, 1, refs(), status=state, price_minor=100)
    db.commit()
    before = _bens(db, ben.org_id)
    base = f"/v1/organizations/{ben.org_id}"

    packs = ben.get("/v1/workflow-packs")
    assert key not in {p["slug"] for p in packs.json()}
    detail = ben.get(f"/v1/workflow-packs/{key}")
    unknown = ben.get(f"/v1/workflow-packs/{key}-none").json()  # it names only the slug Ben asked for
    assert detail.status_code == 404
    assert detail.json() == {**unknown, "detail": unknown["detail"].replace(f"{key}-none", key)}
    hire = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert _code(ben.post(f"{base}/agent-installations", json=hire)) == (404, "NOT_FOUND")
    assert _code(ben.post(f"{base}/agent-installations/{key}:upgrade")) == (404, "NOT_FOUND")
    start = {"packSlug": key, "input": INPUT, "budgetMinor": 1500}
    assert _code(ben.post("/v1/workflow-runs", json=start)) == (404, "NOT_FOUND")
    assert _bens(db, ben.org_id) == before and starts.calls == []

    connections = ben.get("/v1/connections")
    assert connections.status_code == 200
    leaks = [r.text for r in (packs, connections) if key in r.text or PACK_V1 in r.text]
    assert leaks == [], leaks
    assert ben.get(f"{base}/studio/listings/{listing}").status_code == 404
    assert ben.get(f"{base}/studio/listings").json() == []
    assert ben.get(f"{base}/studio/packs/{key}").status_code == 404


def _month_form(db, org_id: str, key: str) -> None:
    """The publisher's next contract takes a month instead of v1's dates (a different start form)."""
    schema = f"{key.split('--')[0]}--recon-month"
    registry.claim(db, "schema", schema, owners.org_owner(org_id), "test")
    month = {"type": "object", "required": ["month"], "properties": {"month": {"type": "string"}}}
    d = Definition(kind="schema", key=schema, body=month, files={}, path=path_for("schema", schema))
    registry.publish(db, d, "test", "a month form", source=registry.BUILDER)
    contract = registry.latest(db, "contract", key)
    body = {**contract.body, "input_schema_ref": schema}
    d = Definition(kind="contract", key=key, body=body, files={}, path=path_for("contract", key))
    registry.publish(db, d, "test", "v2 takes a month", source=registry.BUILDER)


@pytest.mark.parametrize("state", NEVER_APPROVED)
def test_a_buyer_holding_v1_never_reaches_a_newer_unapproved_version(live, ana, ben, starts, db, state):  # noqa: F811
    key, refs = _pack(db, ana.org_id)
    listing = add_listing(db, "pack", key, ana.org_id, name=PACK_V1)
    v1 = add_version(db, listing, 1, refs(), price_minor=100)
    approve_and_list(db, listing, v1)
    db.commit()
    _add(ben, key)
    # v2: a new name, a new start form and a new price, in `state`.
    _month_form(db, ana.org_id, key)
    _republish(db, "pack", key, PACK_V2)
    v2 = add_version(db, listing, 2, refs(), status=state, price_minor=999)
    db.commit()
    before = _bens(db, ben.org_id)
    base = f"/v1/organizations/{ben.org_id}"

    packs = ben.get("/v1/workflow-packs")
    row = {p["slug"]: p for p in packs.json()}[key]
    assert row["name"] == PACK_V1
    assert (row["listing"]["version"], row["listing"]["installedVersion"]) == (1, 1)
    assert row["listing"]["fee"]["amountMinor"] == 100 and row["listing"]["updateAvailable"] is False
    detail = ben.get(f"/v1/workflow-packs/{key}")
    assert detail.status_code == 200 and detail.json()["name"] == PACK_V1
    assert detail.json()["inputSchema"]["required"] == V1_START_FORM
    hire = {"packSlug": key, "capMinor": 2000, "reviewerPool": "team"}
    assert ben.post(f"{base}/agent-installations", json=hire).status_code == 201  # saves v1's settings
    assert _code(ben.post(f"{base}/agent-installations/{key}:upgrade")) == (409, "UP_TO_DATE")
    assert _bens(db, ben.org_id) == before

    run = ben.post("/v1/workflow-runs", json={"packSlug": key, "input": INPUT, "budgetMinor": 1500})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    [pinned] = _rows(db, "SELECT snapshot FROM runs WHERE id = %s", run_id)
    versions = {(v["kind"], v["key"]): v["version"] for v in pinned["snapshot"]["versions"]}
    assert versions[("pack", key)] == 1 and versions[("contract", key)] == 1
    assert pinned["snapshot"]["defs"]["pack"][key]["body"]["name"] == PACK_V1
    assert pinned["snapshot"]["fees"]["pack"]["version_id"] == v1
    fees = _rows(
        db,
        "SELECT run_id, amount_minor, listing_version_id FROM fee_lines WHERE buyer_org_id = %s",
        ben.org_id,
    )
    assert [tuple(f.values()) for f in fees] == [(run_id, 100, v1)]

    connections = ben.get("/v1/connections")
    assert connections.status_code == 200 and PACK_V1 in connections.text
    receipt = ben.get(f"/v1/workflow-runs/{run_id}/receipt")
    seen = [packs.text, detail.text, connections.text, receipt.text]
    leaks = [t for t in seen if PACK_V2 in t or v2 in t or '"amountMinor":999' in t or '"month"' in t]
    assert leaks == [], leaks
    assert ben.get(f"{base}/studio/listings/{listing}").status_code == 404


def test_a_withdrawn_pack_cannot_run_and_its_grants_stay_with_the_installation(live, ana, ben, starts, db):  # noqa: F811
    key, refs = _pack(db, ana.org_id)
    listing = add_listing(db, "pack", key, ana.org_id, name=PACK_V1)
    approve_and_list(db, listing, add_version(db, listing, 1, refs(), price_minor=100))
    db.commit()
    _add(ben, key)
    granted = ben.get("/v1/connections").json()
    assert ops_post(live, f"/v1/ops/listings/{listing}:unlist", reason="Reported broken").status_code == 200
    before = _bens(db, ben.org_id)
    base = f"/v1/organizations/{ben.org_id}"

    assert key not in {p["slug"] for p in ben.get("/v1/workflow-packs").json()}
    assert _code(ben.get(f"/v1/workflow-packs/{key}")) == (404, "NOT_FOUND")
    assert _code(ben.post(f"{base}/agent-installations/{key}:upgrade")) == (404, "NOT_FOUND")
    start = {"packSlug": key, "input": INPUT, "budgetMinor": 1500}
    assert _code(ben.post("/v1/workflow-runs", json=start)) == (404, "NOT_FOUND")
    assert _bens(db, ben.org_id) == before and starts.calls == []
    # The connections keep the grants Ben's installation was given (only their order changes, as no pack he
    # can see uses these apps any more); the installation stays, and nothing can run under those grants.
    after = ben.get("/v1/connections").json()
    assert sorted(after, key=lambda c: c["key"]) == sorted(granted, key=lambda c: c["key"])
    assert {g["install"] for c in after for g in c["grants"]} == {PACK_V1}


# --- agents -----------------------------------------------------------------------------------------------


def _studio_agent(publisher: As) -> str:
    """Ana's agent saved in the Studio, as version 1."""
    made = publisher.post(
        f"/v1/organizations/{publisher.org_id}/studio/agents", json=TEAM_AGENT.model_dump(by_alias=True)
    )
    assert made.status_code == 201, made.text
    return made.json()["key"]


# The agent paths, over every state: never approved (absent, as only listed definitions reach another
# workspace's bundle), unlisted (absent again, as withdrawal empties `listed_definitions`), and listed at v1
# with v2 in review or refused (v1 everywhere, as `listed_definitions` holds only the approved version).
@pytest.mark.parametrize("state", STATES)
def test_a_buyer_never_reaches_an_unapproved_agent_version(live, ana, ben, db, state):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    db.commit()
    agent = _studio_agent(ana)
    _stage(live, db, "agent", agent, ana.org_id, state, lambda: defs_of(db, [("agent", agent)]), AGENT_V2)
    listed = state in NEWER
    seen = []

    agents = ben.get("/v1/agents")
    one = ben.get(f"/v1/agents/{agent}")
    palette = ben.get(f"/v1/organizations/{ben.org_id}/studio/palette")
    seen += [agents.text, one.text, palette.text]
    row = {a["id"]: a for a in agents.json()}.get(agent)
    in_palette = {a["key"]: a for a in palette.json()["agents"]}.get(agent)
    ctx = studio._context(db, ben.org_id)
    draft = invoice_nudges(agent).model_dump(by_alias=True, exclude_none=True)
    check = ben.post(f"/v1/organizations/{ben.org_id}/studio/packs:validate", json=draft)
    assert check.status_code == 200, check.text
    if listed:
        assert row["name"] == AGENT_V1 and row["listing"]["fee"]["amountMinor"] == 100
        assert one.status_code == 200 and one.json()["name"] == AGENT_V1
        assert in_palette["name"] == AGENT_V1 and ctx.agents[agent]["name"] == AGENT_V1
        assert check.json()["ok"] is True, check.text
    else:
        assert row is None and one.status_code == 404 and in_palette is None and agent not in ctx.agents
        assert check.json()["ok"] is False and "plan" in {i.get("step") for i in check.json()["issues"]}
    assert ben.get(f"/v1/organizations/{ben.org_id}/studio/agents/{agent}").status_code == 404
    assert not any(AGENT_V2 in text for text in seen)
    if not listed:
        assert not any(agent in text for text in (agents.text, palette.text))


# --- org-scoped publishing routes ------------------------------------------------------------------------


def _written(db) -> dict:
    return {
        table: _rows(db, f"SELECT * FROM {table} ORDER BY 1")  # noqa: S608 (fixed table names)
        for table in ("publishers", "listings", "listing_versions", "installations", "runs", "fee_lines")
    }


@pytest.mark.parametrize(
    ("method", "route", "body"),
    [
        ("GET", "publisher", None),
        ("PUT", "publisher", {"name": "Ben took over"}),
        ("DELETE", "publisher", None),
        ("POST", "studio/agents/{agent}/submissions", {"priceMinor": 0, "input": {"note": "x"}}),
        ("POST", "studio/packs/{pack}/submissions", {"priceMinor": 0, "input": INPUT}),
        ("GET", "studio/listings", None),
        ("GET", "studio/listings/{listing}", None),
        ("GET", "studio/earnings", None),
        ("POST", "agent-installations/{pack}:upgrade", None),
    ],
)
def test_another_workspace_cannot_use_a_publishers_routes(live, ana, ben, starts, db, method, route, body):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    pack = clone_pack(db, PACK, ana.org_id, "recon", title=PACK_V1)
    agent = _studio_agent(ana)
    listing = add_listing(db, "pack", pack, ana.org_id)
    approve_and_list(db, listing, add_version(db, listing, 1, defs_of(db, [("pack", pack)]), price_minor=100))
    db.commit()
    before = _written(db)
    path = route.format(agent=agent, pack=pack, listing=listing)
    res = ben.api.request(method, f"/v1/organizations/{ana.org_id}/{path}", json=body, headers=ben.headers)
    assert res.status_code == 403 and res.json()["code"] == "TENANT_SCOPE_DENIED", res.text
    assert _written(db) == before and starts.calls == []


@pytest.mark.parametrize("kind", ["pack", "agent"])
def test_a_member_cannot_submit(live, ana, starts, db, kind):  # noqa: F811
    add_publisher(db, ana.org_id, "Acme Labs")
    pack = clone_pack(db, PACK, ana.org_id, "recon")
    agent = _studio_agent(ana)
    key = pack if kind == "pack" else agent
    db.execute("UPDATE org_members SET role = 'member' WHERE user_id = 'uid_ana'")
    db.commit()
    before = _written(db)
    body = {"priceMinor": 0, "input": INPUT if kind == "pack" else {"note": "x"}}
    res = ana.post(f"/v1/organizations/{ana.org_id}/studio/{kind}s/{key}/submissions", json=body)
    assert res.status_code == 403 and res.json()["code"] == "POLICY_DENIED", res.text
    assert _written(db) == before and starts.calls == []


# --- ops ----------------------------------------------------------------------------------------------------


@pytest.fixture
def queued(ana, db):  # noqa: F811
    """Ana's pack listed at version 1, with version 2 waiting for review."""
    key = clone_pack(db, PACK, ana.org_id, "recon", title=PACK_V1)

    def refs() -> list[dict]:
        return defs_of(db, [("pack", key), ("workflow", key), ("contract", key)])

    listing = add_listing(db, "pack", key, ana.org_id)
    approve_and_list(db, listing, add_version(db, listing, 1, refs(), price_minor=100))
    db.commit()
    _republish(db, "pack", key, PACK_V2)
    add_version(db, listing, 2, refs(), price_minor=150)
    db.commit()
    return listing


def _review_state(db) -> dict:
    return {
        table: _rows(db, f"SELECT * FROM {table} ORDER BY 1")  # noqa: S608 (fixed table names)
        for table in ("listings", "listing_versions", "listed_definitions", "ops_audit")
    }


def test_a_customer_token_never_reaches_the_ops_queue(live, ana, queued, db):  # noqa: F811
    before = _review_state(db)
    for res in (
        ana.get("/v1/ops/listings"),
        ana.get(f"/v1/ops/listings/{queued}"),
        *(ana.post(f"/v1/ops/listings/{queued}:{verb}", json={"reason": "Mine"}) for verb in DECISIONS),
    ):
        assert res.status_code == 403, res.text
    assert _review_state(db) == before


def test_support_reads_the_queue_and_decides_nothing(live, queued, db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "")
    monkeypatch.setenv("OPS_SUPPORT_EMAILS", OPS_EMAIL)
    assert queued in {r["id"] for r in live.get("/v1/ops/listings?status=in_review", headers=OPS).json()}
    assert live.get(f"/v1/ops/listings/{queued}", headers=OPS).status_code == 200
    before = _review_state(db)
    for verb in DECISIONS:
        res = ops_post(live, f"/v1/ops/listings/{queued}:{verb}", reason="Support tried")
        assert res.status_code == 403, f"{verb}: {res.text}"
    assert _review_state(db) == before
