import hashlib
import json
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.auth import Actor
from app.errors import ApiProblem
from app.store import Store, locked_store

MAX_KEYS = 1000  # oldest keys are evicted beyond this, so the in-memory cache stays bounded


def _cached(store: Store, slot: str, digest: str) -> tuple[bool, Any]:
    """(True, result) when the slot already holds a result for this body; 409 for a different body."""
    seen = store.idempotency.get(slot)
    if not seen:
        return False, None
    if seen[0] != digest:
        raise ApiProblem(409, "CONFLICT", "This Idempotency-Key was already used with a different request.")
    return True, seen[1]


def _key_lock(store: Store, slot: str, delta: int) -> threading.Lock:
    """The per-key lock, reference counted so it is dropped when nobody holds or waits for it. Call inside
    `locked_store()`."""
    lock, users = store.idempotency_locks.get(slot) or (threading.Lock(), 0)
    users += delta
    if users > 0:
        store.idempotency_locks[slot] = (lock, users)
    else:
        store.idempotency_locks.pop(slot, None)
    return lock


def once(scope: str, actor: Actor, key: str | None, body: BaseModel, make: Callable[[], Any]) -> Any:
    """Same key + same body returns the first result; same key + different body is 409 (API.md section 2).

    Keys are scoped to the caller's org and user, so two people cannot collide on a key. Parallel retries of
    one key wait on that key's own lock, so exactly one of them runs `make()`. The global store lock is held
    only to read and write the cache, never while `make()` runs (a real run start waits on the database and
    Temporal)."""
    if not key:
        return make()
    digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    slot = f"{scope}:{actor.org_id}:{actor.user_id}:{key}"
    with locked_store() as store:
        found, result = _cached(store, slot, digest)
        if found:
            return result
        lock = _key_lock(store, slot, +1)
    try:
        with lock:
            with locked_store() as store:
                found, result = _cached(store, slot, digest)
            if found:
                return result
            result = make()
            with locked_store() as store:
                store.idempotency[slot] = (digest, result)
                while len(store.idempotency) > MAX_KEYS:
                    store.idempotency.popitem(last=False)
            return result
    finally:
        with locked_store() as store:
            _key_lock(store, slot, -1)
