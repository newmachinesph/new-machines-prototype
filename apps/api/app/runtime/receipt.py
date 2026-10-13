"""Hash-chained work receipts: each entry's hash covers the previous hash and the canonical entry.

Functions run on the caller's connection and never commit.
"""

import hashlib
import json
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.defs.digest import canonical

GENESIS = "sha256:" + "0" * 64


def _at(value: datetime) -> str:
    """One fixed text form for `at`, so a timestamp read back from Postgres hashes identically."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def entry_hash(prev_hash: str, entry: dict) -> str:
    """entry = {seq, at, type, node_id, data}."""
    return "sha256:" + hashlib.sha256(prev_hash.encode() + canonical(entry)).hexdigest()


def append(conn, run_id: str, event_key: str, type: str, node_id: str | None, data: dict) -> dict | None:
    """Append one entry. Idempotent per `event_key` (an activity retry returns None and adds nothing)."""
    if conn.execute("SELECT 1 FROM runs WHERE id = %s FOR UPDATE", (run_id,)).fetchone() is None:
        raise LookupError(f"run {run_id} does not exist")
    exists = conn.execute(
        "SELECT 1 FROM receipt_entries WHERE run_id = %s AND event_key = %s", (run_id, event_key)
    ).fetchone()
    if exists:
        return None
    last = conn.execute(
        "SELECT seq, hash FROM receipt_entries WHERE run_id = %s ORDER BY seq DESC LIMIT 1", (run_id,)
    ).fetchone()
    seq, prev_hash = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
    at = datetime.now(UTC)
    # Round-trip through JSON so the hashed value is exactly what jsonb gives back.
    entry = {
        "seq": seq,
        "at": _at(at),
        "type": type,
        "node_id": node_id,
        "data": json.loads(json.dumps(data)),
    }
    hash_ = entry_hash(prev_hash, entry)
    conn.execute(
        "INSERT INTO receipt_entries (run_id, seq, event_key, at, type, node_id, data, prev_hash, hash) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (run_id, seq, event_key, at, type, node_id, Jsonb(entry["data"]), prev_hash, hash_),
    )
    return {**entry, "run_id": run_id, "event_key": event_key, "prev_hash": prev_hash, "hash": hash_}


def verify(conn, run_id: str) -> tuple[bool, int, str]:
    """Recompute the chain. Returns (ok, entry count, head hash as stored; GENESIS when empty)."""
    rows = conn.execute(
        "SELECT seq, at, type, node_id, data, prev_hash, hash FROM receipt_entries "
        "WHERE run_id = %s ORDER BY seq",
        (run_id,),
    ).fetchall()
    prev, ok = GENESIS, True
    for expected_seq, row in enumerate(rows, start=1):
        entry = {
            "seq": row["seq"],
            "at": _at(row["at"]),
            "type": row["type"],
            "node_id": row["node_id"],
            "data": row["data"],
        }
        if row["seq"] != expected_seq or row["prev_hash"] != prev or entry_hash(prev, entry) != row["hash"]:
            ok = False
            break
        prev = row["hash"]
    return ok, len(rows), rows[-1]["hash"] if rows else GENESIS
