from app.store import get_store, reset_store


def test_store_loads_every_fixture():
    s = reset_store()
    assert len(s.packs) == 11  # 7 published seeds plus 4 ops listings (see test_ops_catalog)
    assert sum(x.status == "published" for x in s.pack_listings.values()) == 7
    assert "run_1042" in s.runs
    assert s.runs["run_1042"].deliverable is not None
    assert {r.id for r in s.run_summaries} >= {"run_1047", "run_1033"}
    assert s.tasks["ht_011"].buyer == "A US home goods retailer"
    assert s.org.id == "org_hp01"
    assert s.attention[0].href == "/app/approvals"


def test_money_round_trips_in_camel_case():
    s = reset_store()
    dumped = s.runs["run_1042"].model_dump(by_alias=True, exclude_none=True)
    assert dumped["spent"]["human"] == {"amountMinor": 750, "currency": "USD"}
    assert "endedAt" in dumped and "ended_at" not in dumped


def test_reset_gives_a_fresh_copy():
    s = get_store()
    s.approvals[0].status = "GRANTED"
    assert reset_store().approvals[0].status == "PENDING"
