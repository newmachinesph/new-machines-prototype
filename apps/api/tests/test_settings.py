"""Settings import from any install layout: the API image has only /app/app/settings.py, three levels deep."""

import importlib.util
import shutil
from pathlib import Path

import pytest

from app import settings

SOURCE = Path(settings.__file__)


def _load_copy(root: Path):
    """Import a copy of settings.py placed at <root>/app/settings.py, as the image lays it out."""
    target = root / "app" / "settings.py"
    target.parent.mkdir(parents=True)
    shutil.copy(SOURCE, target)
    spec = importlib.util.spec_from_file_location("settings_copy", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_defaults_resolve_from_a_shallow_install(tmp_path, monkeypatch):
    monkeypatch.delenv("NM_DEFS_DIR", raising=False)
    monkeypatch.delenv("NM_SCHEMAS_DIR", raising=False)
    (tmp_path / "definitions" / "_schemas").mkdir(parents=True)
    module = _load_copy(tmp_path)
    assert module.defs_dir() == tmp_path / "definitions"
    assert module.schemas_dir() == tmp_path / "definitions" / "_schemas"


def test_missing_definitions_do_not_break_import(tmp_path, monkeypatch):
    monkeypatch.delenv("NM_DEFS_DIR", raising=False)
    root = tmp_path / "x"  # nothing named `definitions` above it except what pytest's tmp tree may hold
    module = _load_copy(root)
    found = module.defs_dir()
    assert found.name == "definitions"
    if found.is_dir():  # a stray folder above tmp_path; the walk-up found it, which is its job
        pytest.skip("a definitions folder exists above the temp directory")
    assert found == root / "definitions"


def test_env_overrides_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NM_DEFS_DIR", str(tmp_path / "defs"))
    monkeypatch.setenv("NM_SCHEMAS_DIR", str(tmp_path / "schemas"))
    assert settings.defs_dir() == tmp_path / "defs"
    assert settings.schemas_dir() == tmp_path / "schemas"


def test_checkout_default_is_the_repo_definitions():
    assert SOURCE.resolve().parents[3] / "definitions" == settings._DEFAULT_DEFS_DIR
    assert settings._DEFAULT_DEFS_DIR.is_dir()
