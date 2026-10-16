"""Environment access for the runtime stack. Every function reads os.environ at call time."""

import math
import os
from pathlib import Path


def _find_defs_dir(start: Path) -> Path:
    """The nearest `definitions` folder above `start`: <repo>/definitions in a checkout, /app/definitions in
    the API image. With none anywhere, a path next to the app package that does not exist, so the file
    readers serve no definitions instead of the import failing."""
    for parent in start.parents:
        if (parent / "definitions").is_dir():
            return parent / "definitions"
    return start.parent.parent / "definitions"


_DEFAULT_DEFS_DIR = _find_defs_dir(Path(__file__).resolve())


# 127.0.0.1, not localhost: on Windows "localhost" tries ::1 first and stalls ~20s (compose binds IPv4 only).
def database_url() -> str:
    return os.environ.get("NM_DATABASE_URL", "postgresql://nm:nm@127.0.0.1:5442/nm")


def test_database_url() -> str:
    return os.environ.get("NM_TEST_DATABASE_URL", "postgresql://nm:nm@127.0.0.1:5442/nm_test")


def runtime_enabled() -> bool:
    return os.environ.get("NM_RUNTIME", "off") == "temporal"


def temporal_target() -> str:
    return os.environ.get("TEMPORAL_TARGET", "127.0.0.1:7243")


def temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def temporal_api_key() -> str | None:
    """When set, the connection uses TLS plus this API key (Temporal Cloud, either endpoint style)."""
    return os.environ.get("TEMPORAL_API_KEY") or None


def task_queue() -> str:
    return os.environ.get("NM_TASK_QUEUE", "nm-packs")


def workflow_id_prefix() -> str:
    """Prepended to every run workflow id. Empty in production; databases that share one dev Temporal
    server give each its own prefix so their per-database run ids cannot collide."""
    return os.environ.get("NM_WORKFLOW_ID_PREFIX", "")


def model_env() -> str:
    return os.environ.get("NM_MODEL_ENV", "test")


JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"


def jev_api_key() -> str:
    """The decision model's API key. Never log or return it in a response."""
    return os.environ.get("JEV_API_KEY", "")


def jev_url() -> str:
    return os.environ.get("NM_JEV_URL") or JEV_URL


def jev_model() -> str:
    return os.environ.get("NM_JEV_MODEL") or JEV_MODEL


JEV_USD_PER_MTOK_IN = 3.0  # conservative: used when the endpoint reports no cost
JEV_USD_PER_MTOK_OUT = 15.0


def jev_usd_per_mtok_in() -> float:
    return _positive_float("NM_JEV_USD_PER_MTOK_IN", JEV_USD_PER_MTOK_IN)


def jev_usd_per_mtok_out() -> float:
    return _positive_float("NM_JEV_USD_PER_MTOK_OUT", JEV_USD_PER_MTOK_OUT)


def jev_mode() -> str:
    """off | fake | live. NM_JEV wins (any other set value is off); otherwise fake under the test model env,
    live when a key is set."""
    mode = os.environ.get("NM_JEV", "").strip().lower()
    if mode in ("off", "fake", "live"):
        return mode
    if mode:
        return "off"
    if model_env() == "test":
        return "fake"
    return "live" if jev_api_key() else "off"


def workspace_mode() -> str:
    """demo (default): customer endpoints serve the fixture workspace alongside real data. live: definitions
    and real rows only, never fixture data."""
    return os.environ.get("NM_WORKSPACE") or "demo"


SANDBOX_MODE = "sandbox"  # the connector mode whose tool calls answer from sandbox data


def connector_mode() -> str:
    return os.environ.get("NM_CONNECTOR_MODE", SANDBOX_MODE)


def web_origin() -> str:
    """The customer web app's origin, where app sign-in links return: NM_WEB_ORIGIN, else the first
    ALLOWED_ORIGINS entry (the API's CORS list), else the local web dev server. No trailing slash."""
    given = [os.environ.get("NM_WEB_ORIGIN") or ""] + (os.environ.get("ALLOWED_ORIGINS") or "").split(",")
    origins = [o.strip().rstrip("/") for o in given]
    return next((o for o in origins if o), "http://localhost:3100")


def defs_dir() -> Path:
    raw = os.environ.get("NM_DEFS_DIR")
    return Path(raw) if raw else _DEFAULT_DEFS_DIR


def schemas_dir() -> Path:
    """JSON Schemas for definition kinds; override so a deployed image can point at a copied folder."""
    raw = os.environ.get("NM_SCHEMAS_DIR")
    return Path(raw) if raw else defs_dir() / "_schemas"


def model_api_key() -> str | None:
    return os.environ.get("MODEL_API_KEY") or None


def demo_user_uid() -> str | None:
    """The demo user's Firebase uid; Composio connections are owned by this user id."""
    return os.environ.get("DEMO_USER_UID") or None


def composio_api_key() -> str | None:
    """Composio project key: real app connections in the live workspace (and the demo's live connector
    mode)."""
    return os.environ.get("COMPOSIO_API_KEY") or None


def secrets_key() -> str | None:
    """NM_SECRETS_KEY: 32 bytes, URL-safe base64, that seals the tokens of the orgs' own MCP servers
    (AES-GCM). Unset, nothing is sealed or opened (`secrets_box` fails closed)."""
    return os.environ.get("NM_SECRETS_KEY") or None


def defs_auto_apply() -> bool:
    return os.environ.get("NM_DEFS_AUTO_APPLY", "").lower() in {"1", "true", "yes", "on"}


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 1 else default


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def embedded_worker() -> bool:
    """With the runtime on, run the PackRunner worker inside the API process (one Cloud Run service)."""
    return os.environ.get("NM_EMBEDDED_WORKER", "").lower() in {"1", "true", "yes", "on"}


def worker_concurrency() -> int:
    """Concurrent activities (and activity threads) per worker; each holds at most one pooled connection."""
    return _positive_int("NM_WORKER_CONCURRENCY", 8)


def db_pool_max() -> int:
    """Largest Postgres pool this process opens."""
    return _positive_int("NM_DB_POOL_MAX", 8)
