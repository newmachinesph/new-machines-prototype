"""Writes apps/api/openapi.json, the contract the web client is generated from."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
# Only the schema is needed, so skip the sign-in config check.
os.environ.setdefault("AUTH_MODE", "dev")

from app.main import create_app  # noqa: E402

out = Path(__file__).parents[1] / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote {out}")
