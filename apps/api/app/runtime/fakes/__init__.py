"""Fake-model scripts for the sample packs, one module per pack.

A module defines AGENTS (agent id -> script(inputs) -> result, valid against the agent's output schema) and
JEV (decision-model question name -> script(state text) -> raw answer). Modules whose name starts with "_"
are helpers. Used by the fake provider (NM_MODEL_ENV=test) and the fake decision model (NM_JEV=fake).
"""

import importlib
import pkgutil
from collections.abc import Callable, Iterable
from functools import cache
from types import ModuleType


def _collect(modules: Iterable) -> tuple[dict[str, Callable], dict[str, Callable]]:
    agents: dict[str, Callable] = {}
    answers: dict[str, Callable] = {}
    for module in modules:
        for target, found, kind in (
            (agents, getattr(module, "AGENTS", {}), "agent"),
            (answers, getattr(module, "JEV", {}), "question"),
        ):
            for name, script in found.items():
                if name in target:
                    raise ValueError(f"fake {kind} {name!r} is defined twice")
                target[name] = script
    return agents, answers


def _modules() -> list[ModuleType]:
    return [
        importlib.import_module(f"{__name__}.{info.name}")
        for info in pkgutil.iter_modules(__path__)
        if not info.name.startswith("_")
    ]


@cache
def _registry() -> tuple[dict[str, Callable], dict[str, Callable]]:
    return _collect(_modules())


def agent_script(agent_id: str) -> Callable[[dict], dict] | None:
    return _registry()[0].get(agent_id)


def jev_answer(question: str) -> Callable[[str], dict] | None:
    return _registry()[1].get(question)
