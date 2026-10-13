"""Memory spaces: items in Postgres, recalled with full-text search. Functions never commit.

An item with an `org_id` belongs to that org; an item without one is shared only when its source is in
`SHARED_SOURCES` (the definition seed and operator console additions). Runs recall active items only."""

import re
import secrets

_COLUMNS = "id, space, text, source, created_by, created_at"
_WORD = re.compile(r"[^\W_]+")  # letters and digits (any script)
SHARED_SOURCES = ("seed", "console")
# The items an org may read: its own, plus the shared ones (named parameters `org` and `shared`).
READABLE_BY_ORG = "(org_id = %(org)s OR (org_id IS NULL AND source = ANY(%(shared)s)))"


def _scope(org_id: str | None) -> tuple[str, dict]:
    """SQL condition and parameters for the items a run may recall: active ones that `org_id` may read.
    Without an org it fails closed: shared items only."""
    return f"status = 'active' AND {READABLE_BY_ORG}", {"org": org_id, "shared": list(SHARED_SOURCES)}


def _item(row: dict) -> dict:
    return {
        "id": row["id"],
        "space": row["space"],
        "text": row["text"],
        "source": row["source"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
    }


def _newest(conn, space: str, limit: int | None, org_id: str | None = None) -> list[dict]:
    where, params = _scope(org_id)
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM memory_items WHERE space = %(space)s AND {where} "
        "ORDER BY created_at DESC, id DESC LIMIT %(limit)s",
        {**params, "space": space, "limit": limit},
    ).fetchall()
    return [_item(r) for r in rows]


def _any_word(query: str) -> str:
    """A tsquery source that matches any word of `query`. Only letters and digits survive, so the text can
    never inject tsquery operators."""
    return " | ".join(_WORD.findall(query.lower()))


def recall(conn, space: str, query: str, limit: int = 8, org_id: str | None = None) -> list[dict]:
    """Active items of `space` matching any word of `query`, best first; the newest items when none match.
    Only the items `org_id` may read: its own and the shared ones (shared only, without an org)."""
    terms = _any_word(query)
    where, params = _scope(org_id)
    rows = []
    if terms:
        rows = conn.execute(
            f"SELECT {_COLUMNS}, ts_rank(tsv, q) AS rank "
            "FROM memory_items, to_tsquery('english', %(terms)s) AS q "
            f"WHERE space = %(space)s AND tsv @@ q AND {where} "
            "ORDER BY rank DESC, created_at DESC LIMIT %(limit)s",
            {**params, "terms": terms, "space": space, "limit": limit},
        ).fetchall()
    if rows:
        return [_item(r) for r in rows]
    return _newest(conn, space, limit, org_id)


def remember(conn, space: str, text: str, source: str, actor: str, org_id: str | None = None) -> dict:
    """Add an item; `org_id` is the org it belongs to (a run's org), None for a shared item."""
    # clock_timestamp(), not now(): items added in one transaction still get a distinct, ordered time.
    row = conn.execute(
        "INSERT INTO memory_items (id, space, text, source, created_by, created_at, org_id) "
        f"VALUES (%s, %s, %s, %s, %s, clock_timestamp(), %s) RETURNING {_COLUMNS}",
        (f"mem_{secrets.token_hex(6)}", space, text, source, actor, org_id),
    ).fetchone()
    return _item(row)


def list_items(conn, space: str) -> list[dict]:
    """Every item of the space, whatever its org or status (the operator console)."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM memory_items WHERE space = %s ORDER BY created_at DESC, id DESC", (space,)
    ).fetchall()
    return [_item(r) for r in rows]


def delete_item(conn, item_id: str) -> bool:
    return conn.execute("DELETE FROM memory_items WHERE id = %s", (item_id,)).rowcount > 0
