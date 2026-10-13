"""Memory spaces: items in Postgres, recalled with full-text search. Functions never commit."""

import re
import secrets

_COLUMNS = "id, space, text, source, created_by, created_at"
_WORD = re.compile(r"[^\W_]+")  # letters and digits (any script)


def _item(row: dict) -> dict:
    return {
        "id": row["id"],
        "space": row["space"],
        "text": row["text"],
        "source": row["source"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
    }


def _newest(conn, space: str, limit: int | None) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM memory_items WHERE space = %s ORDER BY created_at DESC, id DESC LIMIT %s",
        (space, limit),
    ).fetchall()
    return [_item(r) for r in rows]


def _any_word(query: str) -> str:
    """A tsquery source that matches any word of `query`. Only letters and digits survive, so the text can
    never inject tsquery operators."""
    return " | ".join(_WORD.findall(query.lower()))


def recall(conn, space: str, query: str, limit: int = 8) -> list[dict]:
    """Items of `space` matching any word of `query`, best first; the newest items when none match."""
    terms = _any_word(query)
    rows = []
    if terms:
        rows = conn.execute(
            f"SELECT {_COLUMNS}, ts_rank(tsv, q) AS rank "
            "FROM memory_items, to_tsquery('english', %s) AS q "
            "WHERE space = %s AND tsv @@ q ORDER BY rank DESC, created_at DESC LIMIT %s",
            (terms, space, limit),
        ).fetchall()
    if rows:
        return [_item(r) for r in rows]
    return _newest(conn, space, limit)


def remember(conn, space: str, text: str, source: str, actor: str) -> dict:
    # clock_timestamp(), not now(): items added in one transaction still get a distinct, ordered time.
    row = conn.execute(
        "INSERT INTO memory_items (id, space, text, source, created_by, created_at) "
        f"VALUES (%s, %s, %s, %s, %s, clock_timestamp()) RETURNING {_COLUMNS}",
        (f"mem_{secrets.token_hex(6)}", space, text, source, actor),
    ).fetchone()
    return _item(row)


def list_items(conn, space: str) -> list[dict]:
    return _newest(conn, space, None)


def delete_item(conn, item_id: str) -> bool:
    return conn.execute("DELETE FROM memory_items WHERE id = %s", (item_id,)).rowcount > 0
