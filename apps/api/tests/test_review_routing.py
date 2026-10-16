"""Sub-project B, part 3: who sees a human-review task in /work (live workspace). Ana's org owns the tasks,
Nina reviews for the network from her own org, Ben is another org's owner who never sees Ana's tasks."""

from datetime import UTC, datetime, timedelta

import pytest

from app import review_routing
from app.errors import ApiProblem
from app.redaction import scrub
from app.routers import tasks
from tests.test_live_catalog import PACK, As, _rows
from tests.workforce_seed import (
    SHOWN,
    add_run,
    add_task,
    allow_network,
    hire,
    ids,
    join_network,
    live_api,
    public_id,
)

OLD = timedelta(minutes=31)
OTHER_PACK = "refund-triage"
REVIEW = {"verdict": "APPROVED", "feedbackText": "Checked.", "recordCalls": {"#1003": "explained"}}


@pytest.fixture
def setup(db, monkeypatch):
    return live_api(db, monkeypatch)


@pytest.fixture
def ana(setup) -> As:
    return As(setup[0], "ana")


@pytest.fixture
def ben(setup) -> As:
    return As(setup[0], "ben")


@pytest.fixture
def nina(setup, db) -> As:
    user = As(setup[0], "nina")
    join_network(db, "uid_nina")
    return user


def _task(db, org_id, pool, *, age=timedelta(0), payload=None, allow=True, task_id="ht_1", pack=PACK) -> None:
    hire(db, org_id, pool, pack)
    allow_network(db, org_id, allow)
    add_run(db, org_id, f"run_{task_id}", pack)
    add_task(db, task_id, f"run_{task_id}", at=datetime.now(UTC) - age, payload=payload)


def _pid(db, task_id: str = "ht_1") -> str:
    """The id a network reviewer addresses the task by."""
    return public_id(db, task_id)


def test_a_team_task_is_seen_only_by_the_orgs_reviewers(ana, ben, nina, db):
    _task(db, ana.org_id, "team", age=OLD)
    assert ids(ana) == ["ht_1"]
    assert ids(nina) == [] and ids(ben) == []
    for task_id in ("ht_1", _pid(db)):
        assert nina.get(f"/v1/human-tasks/{task_id}").status_code == 404
        assert nina.post(f"/v1/human-tasks/{task_id}:claim").status_code == 404
        assert ben.post(f"/v1/human-tasks/{task_id}:claim").status_code == 404


def test_a_member_without_the_reviewer_capability_sees_no_tasks(ana, db):
    _task(db, ana.org_id, "team")
    db.execute("UPDATE org_members SET reviewer = false WHERE user_id = 'uid_ana'")
    db.commit()
    assert ids(ana) == []
    assert ana.get("/v1/human-tasks/ht_1").status_code == 404
    assert ana.post("/v1/human-tasks/ht_1:claim").status_code == 404


def test_a_network_task_goes_to_the_network_not_the_team(ana, nina, db):
    _task(db, ana.org_id, "network")
    assert ids(nina) == [_pid(db)]
    assert ids(ana) == []
    assert ana.get("/v1/human-tasks/ht_1").status_code == 404


def test_the_network_addresses_a_task_by_its_public_id_and_the_team_by_its_id(ana, nina, db):
    _task(db, ana.org_id, "team_then_network", age=OLD)
    pid = _pid(db)
    assert pid.startswith("nt_") and len(pid) == 23 and "ht_1" not in pid
    assert ids(nina) == [pid] and ids(ana) == ["ht_1"]
    # A network reviewer never reaches the task by its id, which carries the run id.
    assert nina.get("/v1/human-tasks/ht_1").status_code == 404
    assert nina.post("/v1/human-tasks/ht_1:claim").status_code == 404
    assert nina.post("/v1/human-tasks/ht_1:submit", json=REVIEW).status_code == 404
    with pytest.raises(ApiProblem) as refused:
        review_routing.claim(nina.org_id, "uid_nina", "ht_1")
    assert refused.value.status == 404
    # The team's paths stay on the task's id; the public id is not one of them.
    assert ana.get("/v1/human-tasks/ht_1").json()["id"] == "ht_1"
    assert ana.get(f"/v1/human-tasks/{pid}").status_code == 404
    assert nina.get(f"/v1/human-tasks/{pid}").json()["id"] == pid
    assert nina.post(f"/v1/human-tasks/{pid}:claim").json()["id"] == pid


def test_every_task_gets_its_own_public_id(ana, db):
    _task(db, ana.org_id, "team")
    for n in range(20):
        add_task(db, f"ht_more_{n}", "run_ht_1")
    rows = _rows(db, "SELECT public_id FROM run_tasks")
    assert len({r["public_id"] for r in rows}) == len(rows) == 21


def test_with_the_switch_off_the_network_is_never_offered_a_task(ana, nina, db):
    _task(db, ana.org_id, "network", allow=False, pack=OTHER_PACK)
    _task(db, ana.org_id, "team_then_network", age=OLD, allow=False, task_id="ht_2")
    assert sorted(ids(ana)) == ["ht_1", "ht_2"]
    assert ids(nina) == []
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404
    assert nina.post(f"/v1/human-tasks/{_pid(db, 'ht_2')}:claim").status_code == 404


def test_a_sandbox_tests_tasks_stay_with_the_team_whatever_the_packs_pool(ana, nina, db):
    """A Studio "Test in sandbox" run of a pack the org added with a network pool is the builder's own test:
    its review task is never offered to the network, now or after the team-then-network delay."""
    _task(db, ana.org_id, "network")
    _task(db, ana.org_id, "team_then_network", age=OLD, task_id="ht_2", pack=OTHER_PACK)
    db.execute("""UPDATE runs SET projection = projection || '{"sandboxTest": true}'""")
    db.commit()
    assert sorted(ids(ana)) == ["ht_1", "ht_2"] and ids(nina) == []
    for task_id in ("ht_1", "ht_2"):
        assert nina.get(f"/v1/human-tasks/{_pid(db, task_id)}").status_code == 404
        assert nina.post(f"/v1/human-tasks/{_pid(db, task_id)}:claim").status_code == 404
    assert ana.get("/v1/human-tasks/ht_1").json()["id"] == "ht_1"


def test_a_run_without_a_hire_row_counts_as_team(ana, nina, db):
    allow_network(db, ana.org_id, True)
    add_run(db, ana.org_id, "run_ht_1")
    add_task(db, "ht_1", "run_ht_1", at=datetime.now(UTC) - timedelta(hours=2))
    assert ids(ana) == ["ht_1"] and ids(nina) == []


@pytest.mark.parametrize(("minutes", "offered"), [(29, False), (31, True)])
def test_team_then_network_reaches_the_network_after_30_minutes(ana, nina, db, minutes, offered):
    _task(db, ana.org_id, "team_then_network", age=timedelta(minutes=minutes))
    assert ids(ana) == ["ht_1"]
    assert ids(nina) == ([_pid(db)] if offered else [])


def test_the_30_minutes_count_from_created_at(ana, nina, db):
    _task(db, ana.org_id, "team_then_network")
    created = _rows(db, "SELECT created_at FROM run_tasks WHERE id = 'ht_1'")[0]["created_at"]

    def seen(now: datetime) -> list[str]:
        return [r["id"] for r in review_routing.visible_rows(nina.org_id, "uid_nina", now=now)]

    assert seen(created + timedelta(minutes=30) - timedelta(seconds=1)) == []
    assert seen(created + timedelta(minutes=30)) == ["ht_1"]
    early = created + timedelta(minutes=29, seconds=59)
    assert review_routing.visible_row(nina.org_id, "uid_nina", _pid(db), now=early) is None
    with pytest.raises(ApiProblem) as refused:
        review_routing.claim(nina.org_id, "uid_nina", _pid(db), now=early)
    assert refused.value.status == 404
    assert review_routing.claim(nina.org_id, "uid_nina", _pid(db), now=created + review_routing.NETWORK_DELAY)


def test_a_task_the_team_claimed_is_never_offered_to_the_network(ana, nina, db):
    _task(db, ana.org_id, "team_then_network")
    assert ana.post("/v1/human-tasks/ht_1:claim").status_code == 200
    db.execute("UPDATE run_tasks SET created_at = now() - interval '2 hours'")
    db.commit()
    assert ids(nina) == []
    assert nina.get(f"/v1/human-tasks/{_pid(db)}").status_code == 404
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404
    assert _rows(db, "SELECT payload->>'claimed_via' AS via, payload->>'pay' AS pay FROM run_tasks") == [
        {"via": "team", "pay": None}
    ]


def test_a_task_the_network_claimed_is_not_claimed_again(ana, nina, db):
    _task(db, ana.org_id, "team_then_network", age=OLD)
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 200
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 200  # her own claim again: no change
    taken = ana.post("/v1/human-tasks/ht_1:claim")
    assert taken.status_code == 409 and taken.json()["code"] == "CONFLICT"
    assert ids(ana) == []  # no longer an offer for the team either


def test_a_disabled_or_suspended_network_reviewer_sees_nothing(ana, nina, db):
    _task(db, ana.org_id, "network")
    join_network(db, "uid_nina", enabled=False)
    assert ids(nina) == []
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404
    join_network(db, "uid_nina", status="suspended")
    assert ids(nina) == []
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404


def test_a_user_who_never_joined_the_network_sees_nothing_of_it(ana, ben, db):
    _task(db, ana.org_id, "network")
    assert ids(ben) == []
    assert ben.get(f"/v1/human-tasks/{_pid(db)}").status_code == 404


def test_a_suspended_orgs_tasks_leave_the_network(ana, nina, db):
    _task(db, ana.org_id, "network")
    db.execute("UPDATE orgs SET status = 'suspended' WHERE id = %s", (ana.org_id,))
    db.commit()
    assert ids(nina) == []
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404


def test_network_reviewers_never_see_their_own_org_through_the_network(nina, db):
    _task(db, nina.org_id, "network")
    assert ids(nina) == []  # Nina owns this org and the pool is network, so the team does not see it either
    for task_id in ("ht_1", _pid(db)):
        assert nina.get(f"/v1/human-tasks/{task_id}").status_code == 404
        assert nina.post(f"/v1/human-tasks/{task_id}:claim").status_code == 404


def test_a_network_reviewer_reaches_their_own_orgs_task_only_as_the_team(nina, db):
    _task(db, nina.org_id, "team_then_network", age=timedelta(hours=2))
    rows = review_routing.visible_rows(nina.org_id, "uid_nina")
    assert [(r["id"], r["via"]) for r in rows] == [("ht_1", "team")]
    claimed = nina.post("/v1/human-tasks/ht_1:claim").json()
    assert claimed["via"] == "team" and claimed["pay"]["amountMinor"] == 0
    assert _rows(db, "SELECT payload->>'claimed_via' AS via, payload->>'pay' AS pay FROM run_tasks") == [
        {"via": "team", "pay": None}
    ]


NOTE = "Ana's workspace asked: call +1 415-555-0100 or write ana@example.com."
LEAKS = (
    "Ana's workspace",
    "ana's workspace",
    "ANA'S WORKSPACE",
    "ana@example.com",
    "555-0100",
    "run_ht_1",  # the other org's run id
    "run_",  # any run id
    "ht_1",  # the task's own id, which carries the run id
)


def _leaky_payload() -> dict:
    return {
        "title": "Review for Ana's workspace",
        "instructions": NOTE,
        "expires_at": "2026-10-15T09:00:00Z",
        "show": [
            {**SHOWN[0], "note": NOTE, "flag": NOTE},
            {**SHOWN[0], "ref": "ANA'S WORKSPACE-77", "counterpart_ref": "ch_ana's workspace", "note": ""},
        ],
    }


def _assert_clean(text: str) -> None:
    for leak in LEAKS:
        assert leak not in text, (leak, text)


def test_network_reviewers_get_a_copy_without_the_org_or_contact_details(ana, nina, db):
    note = "Ana's workspace asked: call +1 415-555-0100 or write ana@example.com."
    payload = {
        "title": "Review for Ana's workspace",
        "instructions": note,
        "show": [{**SHOWN[0], "note": note, "flag": note}],
    }
    _task(db, ana.org_id, "network", payload=payload)
    offer = nina.get("/v1/human-tasks/eligible").json()[0]
    task = nina.get(f"/v1/human-tasks/{_pid(db)}")
    for text in (str(offer), task.text):
        assert "Ana's workspace" not in text
        assert "ana@example.com" not in text and "555-0100" not in text
    body = task.json()
    assert body["via"] == "network" and body["buyer"] == "A New Machines customer"
    assert body["title"] == "Review for the customer"
    assert body["records"][0]["agentNote"] == "the customer asked: call Hidden or write Hidden."
    assert body["pay"]["amountMinor"] == review_routing.NETWORK_PAY_PER_RECORD_MINOR
    assert body["payTerms"] == "Simulated pay: no money moves"


def test_a_review_that_shows_an_object_reads_as_labelled_details(ana, nina, db):
    """A pack built in the Studio often shows an agent's output: one row per key, sent with the task, not
    the offer. The network copy is cleaned like the records; the team's hides contact details only."""
    show = {"request": f"Check order #1001 for Ana's workspace. {NOTE}", "matched": True, "lines": [1, 2]}
    _task(db, ana.org_id, "network", payload={"title": "Review the request", "show": show})
    offer = nina.get("/v1/human-tasks/eligible").json()[0]
    assert "details" not in offer
    task = nina.get(f"/v1/human-tasks/{_pid(db)}")
    _assert_clean(task.text)
    assert task.json()["records"] == []
    cleaned = "Check order #1001 for the customer. the customer asked: call Hidden or write Hidden."
    # Postgres keeps an object's keys in its own order (jsonb), so the rows are compared as a set.
    assert sorted(task.json()["details"], key=lambda r: r["label"]) == [
        {"label": "Lines", "value": "[1, 2]"},
        {"label": "Matched", "value": "true"},
        {"label": "Request", "value": cleaned},
    ]
    row = {
        **_rows(db, "SELECT * FROM run_tasks")[0],
        "via": "team",
        "run_title": "R",
        "org_name": "Ana's workspace",
    }
    own = "Check order #1001 for Ana's workspace. Ana's workspace asked: call Hidden or write Hidden."
    assert {d.label: d.value for d in tasks.real_task(row).details}["Request"] == own


def test_details_are_cleaned_before_they_are_cut_or_shaped():
    """A cut must not leave part of an email address or of the org's name that the cleaning no longer
    recognises, and a key is cleaned before its dashes and underscores become spaces."""

    def clean(text: str) -> str:
        return scrub(text, "Coca-Cola")

    pad = "x" * (tasks.MAX_DETAIL_CHARS - 12)
    show = {"coca-cola_ref": f"{pad} write jane.doe@cocacola.com or Coca-Cola", "lines": [True, None, "a"]}
    rows = {d.label: d.value for d in tasks._details(show, clean)}
    assert "The customer ref" in rows
    long = rows["The customer ref"]
    assert len(long) == tasks.MAX_DETAIL_CHARS and long.endswith("…")
    assert "jane" not in long and "cocacola" not in long and "Coca" not in long
    assert rows["Lines"] == '[true, null, "a"]'
    assert [(d.label, d.value) for d in tasks._details(["a", 2], clean)] == [("Details", '["a", 2]')]
    assert [(d.label, d.value) for d in tasks._details("Check it.", clean)] == [("Details", "Check it.")]

    many = tasks._details({f"k{i}": i for i in range(tasks.MAX_DETAILS + 4)}, clean)
    assert len(many) == tasks.MAX_DETAILS + 1
    assert (many[-1].label, many[-1].value) == ("More", "4 more fields are not shown here.")
    assert tasks._details([{"ref": "r1"}, {"ref": "r2"}], clean) == []  # a list of objects shows as records


def test_a_mixed_list_shows_its_plain_values_as_one_details_row():
    """A list with objects shows the objects as records; a text or a number beside them is not lost: the
    plain values are one "Details" row, cleaned whole before it is cut like any other value."""

    def clean(text: str) -> str:
        return scrub(text, "Coca-Cola")

    mixed = [{"ref": "r1"}, "Call Coca-Cola", 2, None, {"ref": "r2"}, "write jane.doe@cocacola.com"]
    rows = [(d.label, d.value) for d in tasks._details(mixed, clean)]
    assert rows == [("Details", '["Call the customer", 2, "write Hidden"]')]
    one = [(d.label, d.value) for d in tasks._details([{"ref": "r1"}, "Call Coca-Cola", None], clean)]
    assert one == [("Details", "Call the customer")]  # one value shows as itself, not as a list
    assert tasks._details([{"ref": "r1"}, None], clean) == []
    pad = "x" * tasks.MAX_DETAIL_CHARS
    [long] = tasks._details([{"ref": "r1"}, f"{pad} write jane.doe@cocacola.com or Coca-Cola"], clean)
    assert len(long.value) == tasks.MAX_DETAIL_CHARS and long.value.endswith("…")
    assert "jane" not in long.value and "cocacola" not in long.value and "Coca" not in long.value


def test_no_network_response_carries_the_org_or_contact_details(ana, nina, db):
    _task(db, ana.org_id, "network", payload=_leaky_payload())
    db.execute("UPDATE runs SET projection = jsonb_set(projection, '{title}', '\"Ana''s workspace recon\"')")
    db.commit()
    responses = [
        nina.get("/v1/human-tasks/eligible"),
        nina.get(f"/v1/human-tasks/{_pid(db)}"),
        nina.post(f"/v1/human-tasks/{_pid(db)}:claim"),
    ]
    detail = responses[1].json()
    record_ids = [r["id"] for r in detail["records"]]
    assert record_ids == ["#1003", "record-2"]  # an id carrying the org's name is replaced by its position
    review = {**REVIEW, "recordCalls": {"#1003": "explained", "record-2": "refunded"}}
    responses.append(nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=review))
    responses.append(
        nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=review)
    )  # a repeat returns the same copy
    responses.append(nina.get("/v1/reviewer/earnings"))
    for res in responses:
        assert res.status_code == 200, res.text
        _assert_clean(res.text)
    assert detail["packName"] == "the customer recon"
    assert all(res.json()["runId"] == "" for res in responses[1:5])
    assert responses[0].json()[0]["runId"] == ""
    assert detail["records"][1]["order"]["ref"] == "the customer-77"
    assert detail["records"][1]["payment"]["ref"] == "ch_the customer"
    assert responses[3].json()["via"] == "network"
    assert responses[5].json()[0]["title"] == "Review for the customer"
    # Every response names the task by its public id: list, detail, claim, submit (twice) and earnings.
    pid = _pid(db)
    assert responses[0].json()[0]["id"] == pid
    assert [res.json()["id"] for res in responses[1:5]] == [pid] * 4
    assert responses[5].json()[0]["taskId"] == pid
    # The run receives the records' real ids.
    [stored] = _rows(db, "SELECT result->'resolutions' AS res FROM run_tasks")
    assert [(r["order_id"], r["resolution"]) for r in stored["res"]] == [
        ("#1003", "explained"),
        ("ANA'S WORKSPACE-77", "refunded"),
    ]


def test_renamed_record_ids_never_collide_and_reach_the_run_as_their_real_ids(ana, nina, db):
    show = [
        "not a record",
        {"amount_minor": 100},  # no id at all: the reviewer and the run know it as record-2
        {"order_id": "Ana's workspace-1", "amount_minor": 200},  # names the org: renamed
        {**SHOWN[0], "ref": "record-3"},  # a literal ref equal to the renamed id's first choice
    ]
    _task(db, ana.org_id, "network", payload={"show": show})
    detail = nina.get(f"/v1/human-tasks/{_pid(db)}").json()
    shown = [r["id"] for r in detail["records"]]
    assert shown == ["record-2", "record-3-2", "record-3"] and len(set(shown)) == len(shown)
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 200
    calls = {"record-2": "a", "record-3-2": "b", "record-3": "c"}
    assert (
        nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json={**REVIEW, "recordCalls": calls}).status_code
        == 200
    )
    [stored] = _rows(db, "SELECT result->'resolutions' AS res FROM run_tasks")
    assert [(r["order_id"], r["resolution"]) for r in stored["res"]] == [
        ("record-2", "a"),
        ("Ana's workspace-1", "b"),
        ("record-3", "c"),
    ]


def test_item_notes_reach_the_run_under_the_items_real_ids(ana, nina, db):
    """A network reviewer notes items by the ids they were shown; the run reads each note under the item's
    own ref, after the general note. A note on an id the reviewer was not shown is dropped."""
    _task(db, ana.org_id, "network", payload=_leaky_payload())
    shown = [r["id"] for r in nina.get(f"/v1/human-tasks/{_pid(db)}").json()["records"]]
    assert shown == ["#1003", "record-2"]
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 200
    notes = {"record-2": "  Refund it.  ", "#1003": "Fine.", "ghost": "Lost.", "record-1": " "}
    review = {**REVIEW, "recordNotes": notes}
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=review).status_code == 200
    [stored] = _rows(db, "SELECT result->>'note' AS note FROM run_tasks")
    assert stored["note"] == "Checked.\n\n#1003: Fine.\n\nANA'S WORKSPACE-77: Refund it."


def test_no_reviewer_card_shows_an_email_address_and_notes_still_reach_the_item(ana, nina, db):
    """A support email's item ref may be the sender's address: both copies show it hidden, under a
    positional id, and a note on it reaches the run under the real ref."""
    item = {**SHOWN[0], "ref": "jane.doe@example.com", "counterpart_ref": "thread for bob@example.com"}
    _task(db, ana.org_id, "network", payload={"show": [SHOWN[0], item]})
    team = tasks.real_task({**_rows(db, "SELECT * FROM run_tasks")[0], "via": "team", "run_title": "R"})
    network = nina.get(f"/v1/human-tasks/{_pid(db)}")
    for text in (team.model_dump_json(), network.text):
        assert "@" not in text and "jane" not in text and "bob" not in text, text
    [_, record] = network.json()["records"]
    assert record["id"] == "record-2"
    assert (record["order"]["ref"], record["payment"]["ref"]) == ("Hidden", "thread for Hidden")
    assert [r.id for r in team.records] == ["#1003", "record-2"]
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 200
    review = {**REVIEW, "recordNotes": {"record-2": "Spam."}}
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=review).status_code == 200
    [stored] = _rows(db, "SELECT result->>'note' AS note FROM run_tasks")
    assert stored["note"] == "Checked.\n\njane.doe@example.com: Spam."


def test_a_shown_id_standing_for_two_real_ids_is_dropped():
    assert tasks.id_map(["a", "b", "a"], ["x", "y", "z"]) == {"b": "y"}
    assert tasks.id_map(["a", "a"], ["x", "x"]) == {"a": "x"}


def test_the_network_deadline_keeps_its_digits(ana, nina, db):
    _task(db, ana.org_id, "network", payload={"expires_at": "2026-10-15 09:00 for Ana's workspace"})
    assert nina.get(f"/v1/human-tasks/{_pid(db)}").json()["deadline"] == "2026-10-15 09:00 for the customer"


def test_decided_and_claimed_tasks_do_not_crowd_offers_out_of_the_list(ana, db):
    _task(db, ana.org_id, "team", age=timedelta(days=1), task_id="ht_old")
    for n in range(review_routing.LIST_LIMIT + 1):
        add_task(db, f"ht_done_{n}", "run_ht_old", status="resolved")
    add_task(db, "ht_held", "run_ht_old", payload={"claimed_by": "uid_ana", "claimed_via": "team"})
    assert ids(ana) == ["ht_old"]
    assert ana.get("/v1/human-tasks/ht_held").json()["state"] == "CLAIMED"  # still reachable by id


def test_the_team_sees_its_own_copy_unpaid(ana, db):
    _task(db, ana.org_id, "team", payload={"title": "Review for Ana's workspace"})
    body = ana.get("/v1/human-tasks/ht_1").json()
    assert body["via"] == "team" and body["title"] == "Review for Ana's workspace"
    assert body["pay"]["amountMinor"] == 0 and body["payTerms"] == "Team review: unpaid"


def test_a_network_reviewer_claims_submits_and_earns_simulated_pay(setup, ana, ben, nina, db):
    _, signals = setup
    _task(db, ana.org_id, "network")
    assert ben.post(f"/v1/human-tasks/{_pid(db)}:claim").status_code == 404
    claimed = nina.post(f"/v1/human-tasks/{_pid(db)}:claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["state"] == "CLAIMED"
    stored = "SELECT payload->>'claimed_via' AS via, (payload->>'pay')::int AS pay FROM run_tasks"
    assert _rows(db, stored) == [{"via": "network", "pay": 150}]
    assert ids(nina) == []  # claimed, so no longer an open offer
    assert ben.post(f"/v1/human-tasks/{_pid(db)}:submit", json=REVIEW).status_code == 404
    done = nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=REVIEW)
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "SUBMITTED"
    assert signals.human == [("run_ht_1", "ht_1", "resolved")]
    earned = nina.get("/v1/reviewer/earnings").json()
    assert [(e["taskId"], e["amount"]["amountMinor"], e["simulated"], e["via"]) for e in earned] == [
        (_pid(db), 150, True, "network")
    ]
    assert ana.get("/v1/reviewer/earnings").json() == []
    assert ben.get("/v1/reviewer/earnings").json() == []


def test_a_team_reviewer_submits_through_the_routing(setup, ana, db):
    _, signals = setup
    _task(db, ana.org_id, "team_then_network")
    assert ana.post("/v1/human-tasks/ht_1:submit", json=REVIEW).status_code == 409  # not claimed yet
    assert ana.post("/v1/human-tasks/ht_1:claim").status_code == 200
    done = ana.post("/v1/human-tasks/ht_1:submit", json=REVIEW)
    assert done.status_code == 200, done.text
    assert (done.json()["state"], done.json()["via"]) == ("SUBMITTED", "team")
    assert signals.human == [("run_ht_1", "ht_1", "resolved")]
    earned = ana.get("/v1/reviewer/earnings").json()
    assert [(e["taskId"], e["amount"]["amountMinor"], e["via"]) for e in earned] == [("ht_1", 0, "team")]


def test_a_team_review_earns_nothing_whatever_the_task_says(ana, db):
    _task(db, ana.org_id, "team", payload={"pay": {"amountMinor": 9999}})
    assert ana.post("/v1/human-tasks/ht_1:claim").status_code == 200
    assert ana.post("/v1/human-tasks/ht_1:submit", json=REVIEW).status_code == 200
    earned = ana.get("/v1/reviewer/earnings").json()
    assert [(e["taskId"], e["amount"]["amountMinor"], e["via"]) for e in earned] == [("ht_1", 0, "team")]


def test_a_network_claim_keeps_its_pay_after_its_holder_joins_the_org(ana, db):
    # Ana decided a task of her own org that she had claimed through the network before joining it.
    marks = {"claimed_by": "uid_ana", "claimed_via": "network", "pay": 150}
    add_run(db, ana.org_id, "run_ht_1")
    add_task(db, "ht_1", "run_ht_1", status="resolved", payload=marks)
    db.execute("UPDATE run_tasks SET decided_by = 'uid_ana', decided_at = now()")
    db.commit()
    earned = ana.get("/v1/reviewer/earnings").json()
    assert [(e["taskId"], e["amount"]["amountMinor"], e["via"]) for e in earned] == [("ht_1", 150, "network")]


def test_network_pay_is_per_record_shown_with_at_least_one():
    assert review_routing.network_pay_minor({}) == 150
    assert review_routing.network_pay_minor({"show": "x"}) == 150
    assert review_routing.network_pay_minor({"show": [{}, {}, {}]}) == 450


def test_the_network_is_paid_what_its_claim_records_whatever_the_task_says(ana, nina, db):
    _task(db, ana.org_id, "network", payload={"pay": {"amountMinor": 9999}})
    assert nina.get(f"/v1/human-tasks/{_pid(db)}").json()["pay"]["amountMinor"] == 150
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:claim").json()["pay"]["amountMinor"] == 150
    assert nina.post(f"/v1/human-tasks/{_pid(db)}:submit", json=REVIEW).status_code == 200
    assert [e["amount"]["amountMinor"] for e in nina.get("/v1/reviewer/earnings").json()] == [150]


def test_leaving_an_org_returns_the_leavers_claims_to_the_queue(ana, ben, setup, db):
    api = setup[0]
    added = ana.post(f"/v1/organizations/{ana.org_id}/reviewers", json={"email": "rita@example.com"})
    assert added.status_code == 201, added.text
    rita = As(api, "rita")
    assert rita.post(f"/v1/invitations/{ana.org_id}:accept").status_code == 200
    _task(db, ana.org_id, "team")
    assert rita.post("/v1/human-tasks/ht_1:claim").status_code == 200
    add_run(db, ana.org_id, "run_ana")
    add_task(db, "ht_ana", "run_ana", payload={"claimed_by": "uid_ana", "claimed_via": "team"})
    invited = ben.post(
        f"/v1/organizations/{ben.org_id}/invitations", json={"email": "rita@example.com", "role": "Member"}
    )
    assert invited.status_code == 201, invited.text
    assert rita.post(f"/v1/invitations/{ben.org_id}:accept").status_code == 200  # Rita leaves Ana's org
    holders = {
        r["id"]: r["holder"] for r in _rows(db, "SELECT id, payload->>'claimed_by' AS holder FROM run_tasks")
    }
    assert holders == {"ht_1": None, "ht_ana": "uid_ana"}
    assert ids(ana) == ["ht_1"]


# --- redaction --------------------------------------------------------------------------------------------


def test_scrub_replaces_the_org_name_as_a_whole_word_in_any_case():
    assert (
        scrub("Al asked Always about AL's payout", "Al")
        == "the customer asked Always about the customer's payout"
    )
    assert scrub("Acme Corp. paid acme corp.", "Acme Corp.") == "the customer paid the customer"
    assert scrub("x(Acme)y", "(Acme)") == "xthe customery"
    assert scrub("ch_acme and Acme2", "Acme") == "ch_the customer and Acme2"
    assert scrub("Mail al@example.com", None) == "Mail Hidden"
    assert scrub("Totally fine", "  ") == "Totally fine"
