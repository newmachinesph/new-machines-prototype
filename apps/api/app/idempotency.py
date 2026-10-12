import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.auth import Actor
from app.errors import ApiProblem
from app.store import locked_store

MAX_KEYS = 1000  # oldest keys are evicted beyond this, so the in-memory cache stays bounded


def once(scope: str, actor: Actor, key: str | None, body: BaseModel, make: Callable[[], Any]) -> Any:
    """Same key + same body returns the first result; same key + different body is 409 (API.md section 2).

    Keys are scoped to the caller's org and user, so two people cannot collide on a key. The store lock is
    held from lookup to store, so parallel retries of one key create exactly one result."""
    if not key:
        return make()
    digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    slot = f"{scope}:{actor.org_id}:{actor.user_id}:{key}"
    with locked_store() as store:
        seen = store.idempotency.get(slot)
        if seen:
            if seen[0] != digest:
                raise ApiProblem(
                    409, "CONFLICT", "This Idempotency-Key was already used with a different request."
                )
            return seen[1]
        result = make()
        store.idempotency[slot] = (digest, result)
        while len(store.idempotency) > MAX_KEYS:
            store.idempotency.popitem(last=False)
        return result
