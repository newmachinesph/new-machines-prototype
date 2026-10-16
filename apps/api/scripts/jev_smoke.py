"""Checks JEV_API_KEY against the configured decision-model endpoint (settings.jev_url() and jev_model(),
overridable with NM_JEV_URL / NM_JEV_MODEL) with one tiny question. The key is sent to that endpoint only.

Prints only the host, the model, the outcome status and the cost (reported or estimated): never the key,
the request or the reply body. From apps/api: `uv run --env-file <path to demo-app/.env> python
scripts/jev_smoke.py`.
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

API_ROOT = str(Path(__file__).parents[1])
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)

from app import settings  # noqa: E402
from app.runtime.jev import HttpJev, JevError  # noqa: E402

QUESTIONS = {
    "is_greeting": {
        "type": "noul",
        "instructions": "Is this text a greeting?",
        "criteria": {"true": "A greeting, such as hello.", "false": "Anything else."},
    }
}


def main() -> None:
    key = settings.jev_api_key()
    if not key:
        print("JEV_API_KEY is not set")
        sys.exit(1)
    url, model = settings.jev_url(), settings.jev_model()
    host = urlparse(url).hostname
    try:
        reply = HttpJev(url, key, model).ask("Hello there, nice to meet you.", QUESTIONS)
    except JevError as exc:
        print(f"{host} {model}: {exc.status} ({exc})")  # messages are a status code or an error type
        sys.exit(1)
    kind = "estimated" if reply.cost_estimated else "reported"
    print(f"{host} {model}: ok, answer shape valid, cost {reply.cost_usd} USD ({kind})")


if __name__ == "__main__":
    main()
