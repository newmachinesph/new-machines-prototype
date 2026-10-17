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
    # GoogleAdkPlugin's Pydantic payload converter imports annotated_types lazily while decoding activity
    # results; passing it through here keeps that import out of the sandbox (and its warning out of the log).
    import annotated_types  # noqa: F401

    from app.custom_mcp import client as mcp_client
    from app.runtime import adk_agent, agent, gateway
    from app.runtime.projection import FAILURE_ROUTES
    from app.runtime.providers import MODEL_ACTIVITY_TIMEOUT_S, ModelTurn
    from app.worker.activities import (
        RUN_SEALED,
        SAFE_ERROR_TYPES,
        STOP_ERROR_TYPES,
        AgentResult,
        Failure,
        ItemCall,
        ModelCall,
        NodeCall,
        PackActivities,
        TaskDecision,
        ToolUse,
        run_budget_minor,
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
# An outside call may run to the MCP client's own deadline: the activity must outlast it (plus database time),
# or Temporal retries a call the server is still running.
_TOOL_TIMEOUT = timedelta(seconds=mcp_client.TIMEOUT_S + 15)
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


def _output_truncated(max_turns: int) -> str:
    return f"OUTPUT_TRUNCATED: every answer was cut off at the output limit, {max_turns} model turns"


def _output_invalid(max_turns: int, errors: list[str]) -> str:
    return (
        f"OUTPUT_INVALID: the last result did not match the output schema, {max_turns} model turns: "
        + "; ".join(errors)
    )


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


def _stops_run(err: Exception) -> bool:
    """An activity refused a step for a cap (`STOP_ERROR_TYPES`): the run stops, whatever the error route."""
    cause = err.cause if isinstance(err, ActivityError) else None
    return isinstance(cause, ApplicationError) and cause.type in STOP_ERROR_TYPES


def _route_reason(node: dict, route: str, output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("explanation"), str):
        return output["explanation"]  # a decision explains its own route
    return _ROUTE_REASONS.get((node["type"], route), f"{node['id']} ended with {route}.")


def unlocked_nodes(node: dict) -> list[str]:
    """The nodes a granted approval lets through the gateway: its `granted` target, plus the connector nodes
    its `config.also_unlocks` names (one approval covering a chain of writes)."""
    target = (node.get("routes") or {}).get("granted")
    also = (node.get("config") or {}).get("also_unlocks") or []
    return [n for n in [target, *also] if isinstance(n, str) and n]


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
        self._spent_fees = 0  # agent calls' publisher fees (`start_agent`), within the same budget
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
        self._budget = run_budget_minor(self._snapshot)
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
                fatal = (isinstance(err, _NodeFailed) and err.fatal) or _stops_run(err)
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
        if node["type"] == "connector" and "for_each" in (node.get("config") or {}):
            return await self._for_each(node["id"], attempt)
        side_effects = node["type"] in _SIDE_EFFECT_NODES
        done = await self._act(
            PackActivities.run_node, self._node_call(node["id"], attempt), side_effects=side_effects
        )
        return done["output"], done["route"]

    async def _for_each(self, node_id: str, attempt: int) -> tuple[Any, str]:
        """A connector node with `for_each`: resolve every item's args first, then one side-effecting
        activity per item (each commits its own tool.call), then complete the node. The first denied or
        failed item ends the node with its route; later items are not called."""
        planned = await self._act(PackActivities.plan_for_each, self._node_call(node_id, attempt))
        if planned["route"] is not None:
            return None, planned["route"]
        approved = bool((self._state.get("approvals") or {}).get(node_id))
        results = []
        for index, args in enumerate(planned["items"]):
            item = ItemCall(
                self._run_id, self._snapshot, node_id, attempt, self._next_step(), index, args, approved
            )
            done = await self._act(PackActivities.for_each_call, item, side_effects=True)
            if done["route"] is not None:
                return None, done["route"]
            results.append(done["data"])
        finish = AgentResult(self._run_id, self._snapshot, node_id, attempt, self._next_step(), results)
        done = await self._act(PackActivities.finish_for_each, finish)
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
        self._spent_fees += int(spec.get("fee_minor") or 0)  # runs started before fees return none
        if spec.get("adapter") == "google_adk":
            return await self._adk_agent(node_id, attempt, spec)
        return await self._hosted_agent(node_id, attempt, spec)  # runs pinned before google_adk existed

    async def _adk_agent(self, node_id: str, attempt: int, spec: dict) -> tuple[Any, str]:
        offered = [t["name"] for t in spec["tools"]]

        async def model(system: str, messages: list[dict], tools: list[dict]) -> tuple[list[dict], str]:
            call = ModelCall(
                run_id=self._run_id,
                snapshot=self._snapshot,
                node_id=node_id,
                attempt=attempt,
                step=self._next_step(),
                profile=spec["profile"],
                system=system,
                messages=messages,
                tools=tools,
            )
            turn = await self._act(
                PackActivities.model_call, call, timeout=_MODEL_TIMEOUT, retry=_MODEL_RETRY
            )
            self._spend_ai(int(turn["cost_minor"]))
            return turn["content"], turn["stop_reason"]

        async def tool(block: dict) -> dict:
            use = ToolUse(self._run_id, self._snapshot, node_id, attempt, self._next_step(), block, offered)
            return await self._act(PackActivities.tool_call, use, side_effects=True)

        async def submit(value: Any) -> tuple[Any, str] | adk_agent.Rejected:
            result = AgentResult(self._run_id, self._snapshot, node_id, attempt, self._next_step(), value)
            done = await self._act(PackActivities.finish_node, result)
            if "rejected" in done:  # the model gets the errors back and may submit again
                return adk_agent.Rejected(done["rejected"])
            return done["output"], done["route"]

        hooks = adk_agent.AgentHooks(model=model, tool=tool, submit=submit)
        try:
            return await adk_agent.run_agent(spec, hooks, session_user=self._run_id)
        except adk_agent.TurnsExhausted as exc:
            if exc.rejected:
                raise _NodeFailed(_output_invalid(spec["max_turns"], exc.rejected)) from exc
            raise _NodeFailed(f"TURNS_EXHAUSTED: no result after {spec['max_turns']} model turns") from exc
        except adk_agent.OutputTruncated as exc:
            raise _NodeFailed(_output_truncated(spec["max_turns"])) from exc

    async def _hosted_agent(self, node_id: str, attempt: int, spec: dict) -> tuple[Any, str]:
        messages: list[dict] = list(spec["messages"])
        offered = [t["name"] for t in spec["tools"]]
        kind = ""
        rejected: list[str] = []
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
            self._spend_ai(int(turn["cost_minor"]))
            messages = [*messages, {"role": "assistant", "content": turn["content"]}]
            kind, value = agent.next_step(ModelTurn(turn["content"], turn["stop_reason"], 0, 0, ""))
            if kind == "submit":
                result = AgentResult(self._run_id, self._snapshot, node_id, attempt, self._next_step(), value)
                done = await self._act(PackActivities.finish_node, result)
                if "rejected" not in done:
                    return done["output"], done["route"]
                rejected = done["rejected"]  # the model gets the errors back and may submit again
                feedback = agent.rejected_results(turn["content"], rejected)
                messages.append({"role": "user", "content": feedback})
            elif kind == "truncated":  # a call cut off at the output limit never runs: ask again, shorter
                messages.append({"role": "user", "content": agent.cut_off_results(value)})
            elif kind == "tools":
                blocks = []
                for block in value:
                    use = ToolUse(
                        self._run_id, self._snapshot, node_id, attempt, self._next_step(), block, offered
                    )
                    blocks.append(await self._act(PackActivities.tool_call, use, side_effects=True))
                messages.append({"role": "user", "content": blocks})
            else:
                messages.append({"role": "user", "content": agent.REPROMPT})
        if kind == "truncated":
            raise _NodeFailed(_output_truncated(spec["max_turns"]))
        if rejected:
            raise _NodeFailed(_output_invalid(spec["max_turns"], rejected))
        raise _NodeFailed(f"TURNS_EXHAUSTED: no result after {spec['max_turns']} model turns")

    # --- human tasks and approvals ----------------------------------------------------------------------

    async def _task(self, node: dict, attempt: int) -> tuple[Any, str]:
        node_id = node["id"]
        opened = await self._act(PackActivities.open_task, self._node_call(node_id, attempt))
        if "route" in opened:  # not opened (an approval of a call no longer granted): the node already ended
            return opened.get("output"), opened["route"]
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
        if kind == "approval" and closed["route"] == "granted":
            for unlocked in unlocked_nodes(node):
                self._state["approvals"][unlocked] = True  # the gateway lets that node's tool call through
        return closed["output"], closed["route"]

    # --- helpers ----------------------------------------------------------------------------------------

    def _spend_ai(self, cost_minor: int) -> None:
        """Count a model turn's cost; the node fails for good once the AI spend and the agent fees together
        are over the run's budget."""
        self._spent_ai += cost_minor
        if not self._budget or self._spent_ai + self._spent_fees <= self._budget:
            return
        fees = f" and publisher fees {self._spent_fees}" if self._spent_fees else ""
        verb = "are" if self._spent_fees else "is"
        raise _NodeFailed(
            f"BUDGET_EXCEEDED: AI spend {self._spent_ai}{fees} {verb} over the budget of "
            f"{self._budget} minor units",
            fatal=True,
        )

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
            if side_effects and timeout == _STEP_TIMEOUT:
                timeout = _TOOL_TIMEOUT
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
