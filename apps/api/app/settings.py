"""Environment access for the runtime stack. Every function reads os.environ at call time."""

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
    """Only for Temporal Cloud namespaces (target ending in tmprl.cloud:7233)."""
    return os.environ.get("TEMPORAL_API_KEY") or None


def task_queue() -> str:
    return os.environ.get("NM_TASK_QUEUE", "nm-packs")


def model_env() -> str:
    return os.environ.get("NM_MODEL_ENV", "test")


def connector_mode() -> str:
    return os.environ.get("NM_CONNECTOR_MODE", "sandbox")


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


def defs_auto_apply() -> bool:
    return os.environ.get("NM_DEFS_AUTO_APPLY", "").lower() in {"1", "true", "yes", "on"}
