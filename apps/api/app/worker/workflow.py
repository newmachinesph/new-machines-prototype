"""PackRunner: one generic Temporal workflow that walks any nm.workflow.v1 graph from a pinned snapshot.

The workflow only decides what runs next; every side effect is an activity (see activities.py). State is
the JSON object node configs read with CEL: {"input", "nodes": {<id>: {"output"}}, "memory", "approvals"}.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.exceptions import TimeoutError as ActivityTimeout

with workflow.unsafe.imports_passed_through():
    from app.runtime import agent, gateway
    from app.runtime.projection import FAILURE_ROUTES
    from app.runtime.providers import MODEL_ACTIVITY_TIMEOUT_S, ModelTurn
    from app.worker.activities import (
        RUN_SEALED,
        SAFE_ERROR_TYPES,
        AgentResult,
        Failure,
        ModelCall,
        NodeCall,
        PackActivities,
        TaskDecision,
        ToolUse,
    )

# Retry policies. Changing these values is replay safe: Temporal matches recorded activity commands by type
# and id, not by their retry options.
# Steps with outside side effects (tool calls, connector nodes) keep a short policy: a retry repeats the call.
_RETRY = RetryPolicy(maximum_attempts=3)
# Model turns ride out rate limits and short provider outages: 2s, 4s, 8s, 16s, 30s between six attempts.
_MODEL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=6,
)
# Bookkeeping steps only write Postgres (idempotently, keyed by event): retry until the window below closes,
# so a database blip never leaves a run RUNNING with an unsealed receipt.
_BOOKKEEPING_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=0,
)
_BOOKKEEPING_WINDOW = timedelta(minutes=5)
_STEP_TIMEOUT = timedelta(seconds=30)
_MODEL_TIMEOUT = timedelta(seconds=MODEL_ACTIVITY_TIMEOUT_S)
_SIDE_EFFECT_NODES = {"connector"}
HUMAN_OUTCOMES = {"resolved", "rejected"}
APPROVAL_DECISIONS = {"granted", "denied"}
_ROUTE_REASONS = {
    ("human_workforce", "rejected"): "The reviewer rejected the task.",
    ("human_workforce", "timeout"): "Nobody resolved the reviewer task in time.",
    ("approval", "denied"): "The approval was declined.",
    ("approval", "timeout"): "Nobody answered the approval in time.",
    ("connector", "denied"): "Policy did not permit the tool call.",
    ("connector", "error"): "The tool call failed.",
    ("verification", "fail"): "The result did not pass verification.",
}


@dataclass
class RunInput:
    run_id: str
    snapshot: dict
    input: dict


class _NodeFailed(Exception):
    """A node failed inside the workflow (turns exhausted, budget); `fatal` ignores the error route."""

    def __init__(self, reason: str, fatal: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fatal = fatal


def _activity_reason(node_id: str, err: ActivityError) -> str:
    """`<ErrorType>: <safe message>`; only messages written by our own activities are passed through."""
    cause = err.cause
    if isinstance(cause, ApplicationError):
        kind = cause.type or "Error"
        if kind in SAFE_ERROR_TYPES:
            return f"{kind}: {cause.message}"
        return f"{kind}: the {node_id} step failed"
    if isinstance(cause, ActivityTimeout):
        return f"Timeout: the {node_id} step took too long"
    return f"{type(cause).__name__}: the {node_id} step failed"


def _run_sealed(err: Exception) -> bool:
    cause = err.cause if isinstance(err, ActivityError) else None
    return isinstance(cause, ApplicationError) and cause.type == RUN_SEALED


def _route_reason(node: dict, route: str, output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("explanation"), str):
        return output["explanation"]  # a decision explains its own route
    return _ROUTE_REASONS.get((node["type"], route), f"{node['id']} ended with {route}.")


def _ai_budget(contract: dict, snapshot: dict) -> int:
    """The run's AI budget in minor units: the budget asked for at start, capped by the contract maximum.
    0 means no limit (neither is set)."""
    maximum = int((contract.get("budget") or {}).get("maximum_minor") or 0)
    requested = int(snapshot.get("budget_minor") or 0)
    limits = [b for b in (maximum, requested) if b > 0]
    return min(limits) if limits else 0


def _max_executions(contract: dict, graph: dict) -> int:
    per_node = int((contract.get("limits") or {}).get("max_attempts") or 1)
    limit = per_node * len(graph["nodes"])
    declared = (graph.get("limits") or {}).get("max_total_node_attempts")
    return min(limit, int(declared)) if declared else limit


@workflow.defn(name="PackRunner")
class PackRunner:
    def __init__(self) -> None:
        self._state: dict = {"input": {}, "nodes": {}, "memory": [], "approvals": {}}
        # Keyed by (kind, task id): a signal of the wrong kind can never block or answer another task.
        self._results: dict[tuple[str, str], dict] = {}
        self._status = "RUNNING"
        self._current: str | None = None
        self._waiting: dict | None = None
        self._spent_ai = 0
        self._budget = 0
        self._step = 0
        self._reason: str | None = None
        self._run_id = ""
        self._snapshot: dict = {}
        self._attempt = 1

    # --- signals and query ------------------------------------------------------------------------------

    @workflow.signal
    async def human_result(
        self, task_id: str, outcome: str, note: str, resolutions: list[dict] | None = None
    ) -> None:
        if outcome not in HUMAN_OUTCOMES:
            workflow.logger.warning("ignored human_result %r for %s", outcome, task_id)
            return
        self._results.setdefault(
            ("human", task_id),
            {
                "outcome": outcome,
                "note": note or "",
                "by": None,
                "resolutions": resolutions or [],
            },
        )

    @workflow.signal
    async def approval(self, task_id: str, decision: str, by: str) -> None:
        if decision not in APPROVAL_DECISIONS:
            workflow.logger.warning("ignored approval %r for %s", decision, task_id)
            return
        self._results.setdefault(
            ("approval", task_id),
            {"outcome": decision, "note": "", "by": by or None, "resolutions": []},
        )

    @workflow.query
    def state(self) -> dict:
        return {
            "status": self._status,
            "node": self._current,
            "waiting": self._waiting,
            "spent_ai_minor": self._spent_ai,
            "state": self._state,
        }

    # --- the walk ---------------------------------------------------------------------------------------

    @workflow.run
    async def run(self, inp: RunInput) -> str:
        self._run_id, self._snapshot = inp.run_id, inp.snapshot
        self._state["input"] = inp.input
        graph = next(iter(inp.snapshot["defs"]["workflow"].values()))["body"]
        try:
            return await self._walk(graph)
        except ActivityError as err:
            if _run_sealed(err):  # the run already ended outside this workflow: record nothing more
                raise ApplicationError(str(err.cause), type=RUN_SEALED, non_retryable=True) from err
            # Ending the run failed even after its retries (a long database outage): one more attempt to
            # record the failure and seal the receipt, so the run does not stay open forever.
            node_id = self._current
            reason = _activity_reason(node_id or "run", err)
            workflow.logger.warning("ending run %s failed (%s); retrying once", self._run_id, reason)
            return await self._fail(node_id, self._attempt, reason, node_failed=False)

    async def _walk(self, graph: dict) -> str:
        nodes = {n["id"]: n for n in graph["nodes"]}
        contract = gateway.contract_of(self._snapshot)
        self._budget = _ai_budget(contract, self._snapshot)
        limit = _max_executions(contract, graph)
        attempts: dict[str, int] = {}
        node_id, executions = graph["entry_node_id"], 0
        if node_id not in nodes:  # validation forbids it; a hand-made snapshot must still end cleanly
            reason = f"NO_NODE: entry node {node_id!r} does not exist"
            return await self._fail(None, 1, reason, node_failed=False)
        while True:
            node = nodes[node_id]
            routes = node.get("routes") or {}
            attempt = attempts[node_id] = attempts.get(node_id, 0) + 1
            self._attempt = attempt
            executions += 1
            self._current = node_id
            if executions > limit:
                reason = f"ATTEMPTS_EXCEEDED: more than {limit} node executions"
                return await self._fail(node_id, attempt, reason, node_failed=False)
            if node["type"] == "end":
                return await self._end(node_id, attempt)
            try:
                output, route = await self._execute(node, attempt)
            except (ActivityError, _NodeFailed) as err:
                if _run_sealed(err):  # the run already ended outside this workflow: record nothing more
                    raise ApplicationError(str(err.cause), type=RUN_SEALED, non_retryable=True) from err
                fatal = isinstance(err, _NodeFailed) and err.fatal
                reason = err.reason if isinstance(err, _NodeFailed) else _activity_reason(node_id, err)
                if fatal or "error" not in routes:
                    return await self._fail(node_id, attempt, reason)
                await self._fail(node_id, attempt, reason, route="error", end_run=False)
                output, route, self._reason = None, "error", reason
            else:
                if route in FAILURE_ROUTES:
                    self._reason = _route_reason(node, route, output)
            self._state["nodes"][node_id] = {"output": output}
            if node["type"] == "memory" and (node.get("config") or {}).get("op", "recall") == "recall":
                self._state["memory"] = output
            if routes.get(route) not in nodes:
                reason = f"NO_ROUTE: {node_id} has no route for {route!r}"
                if route in FAILURE_ROUTES and self._reason:  # the node already said why it failed
                    reason = f"{self._reason} ({reason})"
                return await self._fail(node_id, attempt, reason, node_failed=False)
            node_id = routes[route]

    async def _execute(self, node: dict, attempt: int) -> tuple[Any, str]:
        if node["type"] == "agent":
            return await self._agent(node["id"], attempt)
        if node["type"] in ("human_workforce", "approval"):
            return await self._task(node, attempt)
        side_effects = node["type"] in _SIDE_EFFECT_NODES
        done = await self._act(
            PackActivities.run_node, self._node_call(node["id"], attempt), side_effects=side_effects
        )
        return done["output"], done["route"]

    async def _end(self, node_id: str, attempt: int) -> str:
        done = await self._act(
            PackActivities.run_node, self._node_call(node_id, attempt, reason=self._reason)
        )
        self._status = done["output"]["status"]
        self._current = None
        return self._status

    async def _fail(
        self,
        node_id: str,
        attempt: int,
        reason: str,
        *,
        node_failed: bool = True,
        route: str | None = None,
        end_run: bool = True,
    ) -> str:
        failure = Failure(
            run_id=self._run_id,
            node_id=node_id,
            attempt=attempt,
            step=self._next_step(),
            reason=reason,
            route=route,
            node_failed=node_failed,
            end_run=end_run,
        )
        await self._act(PackActivities.fail, failure)
        if end_run:
            self._status, self._current = "FAILED", None
        return "FAILED"

    # --- agent loop -------------------------------------------------------------------------------------

    async def _agent(self, node_id: str, attempt: int) -> tuple[Any, str]:
        spec = await self._act(PackActivities.start_agent, self._node_call(node_id, attempt))
        messages: list[dict] = list(spec["messages"])
        offered = [t["name"] for t in spec["tools"]]
        for _ in range(spec["max_turns"]):
            call = ModelCall(
                run_id=self._run_id,
                snapshot=self._snapshot,
                node_id=node_id,
                attempt=attempt,
                step=self._next_step(),
                profile=spec["profile"],
                system=spec["system"],
                messages=messages,
                tools=spec["tools"],
            )
            turn = await self._act(
                PackActivities.model_call, call, timeout=_MODEL_TIMEOUT, retry=_MODEL_RETRY
            )
            self._spent_ai += int(turn["cost_minor"])
            if self._budget and self._spent_ai > self._budget:
                reason = (
                    f"BUDGET_EXCEEDED: AI spend {self._spent_ai} is over the budget of "
                    f"{self._budget} minor units"
                )
                raise _NodeFailed(reason, fatal=True)
            messages = [*messages, {"role": "assistant", "content": turn["content"]}]
            kind, value = agent.next_step(ModelTurn(turn["content"], turn["stop_reason"], 0, 0, ""))
            if kind == "submit":
                result = AgentResult(self._run_id, self._snapshot, node_id, attempt, self._next_step(), value)
                done = await self._act(PackActivities.finish_node, result)
                return done["output"], done["route"]
            if kind == "tools":
                blocks = []
                for block in value:
                    use = ToolUse(
                        self._run_id, self._snapshot, node_id, attempt, self._next_step(), block, offered
                    )
                    blocks.append(await self._act(PackActivities.tool_call, use, side_effects=True))
                messages.append({"role": "user", "content": blocks})
            else:
                messages.append({"role": "user", "content": agent.REPROMPT})
        raise _NodeFailed(f"TURNS_EXHAUSTED: no result after {spec['max_turns']} model turns")

    # --- human tasks and approvals ----------------------------------------------------------------------

    async def _task(self, node: dict, attempt: int) -> tuple[Any, str]:
        node_id = node["id"]
        opened = await self._act(PackActivities.open_task, self._node_call(node_id, attempt))
        task_id, kind = opened["task_id"], opened["kind"]
        self._waiting = {"task_id": task_id, "kind": kind, "node_id": node_id}
        self._status = "WAITING"
        try:
            await workflow.wait_condition(
                lambda: (kind, task_id) in self._results,
                timeout=timedelta(seconds=opened["timeout_s"]),
            )
            result = self._results[(kind, task_id)]
        except TimeoutError:  # the builtin one: wait_condition timed out
            result = {"outcome": "timeout", "note": "", "by": None, "resolutions": []}
        finally:
            self._waiting, self._status = None, "RUNNING"
        decision = TaskDecision(
            run_id=self._run_id,
            node_id=node_id,
            attempt=attempt,
            step=self._next_step(),
            kind=kind,
            task_id=task_id,
            outcome=result["outcome"],
            note=result["note"],
            by=result["by"],
            resolutions=result["resolutions"],
        )
        closed = await self._act(PackActivities.close_task, decision)
        target = (node.get("routes") or {}).get("granted")
        if kind == "approval" and closed["route"] == "granted" and target:
            self._state["approvals"][target] = True  # the gateway lets that node's tool call through
        return closed["output"], closed["route"]

    # --- helpers ----------------------------------------------------------------------------------------

    def _next_step(self) -> int:
        self._step += 1
        return self._step

    def _node_call(self, node_id: str, attempt: int, reason: str | None = None) -> NodeCall:
        return NodeCall(
            run_id=self._run_id,
            snapshot=self._snapshot,
            node_id=node_id,
            state=self._state,
            attempt=attempt,
            step=self._next_step(),
            reason=reason,
        )

    async def _act(
        self,
        method,
        arg,
        timeout: timedelta = _STEP_TIMEOUT,
        *,
        retry: RetryPolicy | None = None,
        side_effects: bool = False,
    ) -> Any:
        """Run one activity. Without an explicit policy, side-effecting steps get the short one and the rest
        (database bookkeeping) retry within the bookkeeping window."""
        if retry is not None or side_effects:
            return await workflow.execute_activity_method(
                method, arg, start_to_close_timeout=timeout, retry_policy=retry or _RETRY
            )
        return await workflow.execute_activity_method(
            method,
            arg,
            start_to_close_timeout=timeout,
            schedule_to_close_timeout=_BOOKKEEPING_WINDOW,
            retry_policy=_BOOKKEEPING_RETRY,
        )
