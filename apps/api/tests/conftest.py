import os

# The API verifies sign-in unless AUTH_MODE=dev is set explicitly; the suite runs in dev mode by default
# (set before app.main is imported, since importing it builds the app).
os.environ.setdefault("AUTH_MODE", "dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.store import reset_store  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    reset_store()
    return TestClient(create_app())
