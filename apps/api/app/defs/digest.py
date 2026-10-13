"""Canonical JSON and content digests for definitions."""

import hashlib
import json

from app.defs.model import Definition


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(d: Definition) -> str:
    return "sha256:" + hashlib.sha256(canonical({"body": d.body, "files": d.files})).hexdigest()
