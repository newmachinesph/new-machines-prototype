"""Org-owned definitions for the Studio tests: copies of platform definitions published straight into the
registry as an org's own (source "builder")."""

from app.defs import owners, registry
from app.defs.model import Definition, path_for
from app.models.studio import (
    AgentDraft,
    DecisionDefault,
    DecisionRule,
    DecisionRules,
    InputField,
    PackDraft,
    SkillDraft,
    StepDraft,
)


def _own(db, org_id: str, kind: str, key: str, body: dict, files: dict | None = None) -> None:
    registry.claim(db, kind, key, owners.org_owner(org_id), "test")
    d = Definition(kind=kind, key=key, body=body, files=dict(files or {}), path=path_for(kind, key))
    registry.publish(db, d, "test", "team copy for a test", source=registry.BUILDER)


def clone_pack(db, slug: str, org_id: str, name: str, title: str | None = None) -> str:
    """Copy platform pack `slug` (its pack, workflow and contract) as the org's own pack `name`. The copy
    still uses the platform's agents, schemas and decision rules. Returns its key."""
    key = owners.org_key(org_id, name)
    pack = registry.latest(db, "pack", slug).body
    workflow = registry.latest(db, "workflow", pack["workflow"]).body
    contract = registry.latest(db, "contract", pack["contract"]).body
    _own(
        db,
        org_id,
        "pack",
        key,
        {**pack, "slug": key, "name": title or f"Team {pack['name']}", "workflow": key, "contract": key},
    )
    _own(db, org_id, "workflow", key, {**workflow, "workflow_id": key, "work_contract_ref": key})
    _own(db, org_id, "contract", key, {**contract, "contract_id": key})
    db.commit()
    return key


def clone_agent(db, agent: str, org_id: str, name: str, title: str | None = None) -> str:
    """Copy platform agent `agent` as the org's own agent `name`. Returns its key."""
    key = owners.org_key(org_id, name)
    source = registry.latest(db, "agent", agent)
    body = {**source.body, "agent_id": key, "name": title or f"Team {source.body.get('name', agent)}"}
    _own(db, org_id, "agent", key, body, source.files)
    db.commit()
    return key


# The team agent the Studio tests build: it reads open invoices and plans one message per invoice.
TEAM_AGENT = AgentDraft(
    name="Invoice helper",
    summary="Finds the open invoices and plans one short message for each.",
    instructions="You help the accounts team. Work only from the inputs and submit the result in the "
    "required shape.",
    model_profile="fast",
    skills=[
        SkillDraft(
            title="Find open invoices",
            text="Look at every invoice in the inputs whose status is open. Plan one message per invoice "
            "that states its number and the amount due.",
        )
    ],
    tools=["stripe.list_invoices"],
    max_turns=4,
)


def _step(
    id: str, type: str, config: dict | None = None, routes: dict | None = None, rules=None
) -> StepDraft:
    return StepDraft(id=id, type=type, config=config or {}, routes=routes or {}, rules=rules)


def invoice_nudges(agent: str) -> PackDraft:
    """The "Invoice nudges" pack: the team's agent `agent` plans from the open invoices, a person checks the
    plan, the shared writer drafts the emails and, after an approval, they are saved as Gmail drafts."""
    return PackDraft(
        name="Invoice nudges",
        outcome="Every open invoice gets a short, polite nudge, drafted and ready for you to send.",
        description="Reads the open invoices, has the team's agent plan one nudge per invoice and a person "
        "check the plan, then drafts the emails and saves them in Gmail once you approve.",
        human_review="A person on your team checks the planned nudges before any draft is written.",
        input_fields=[InputField(name="as_of", label="As of", type="date")],
        entry_step="start",
        steps=[
            _step("start", "trigger", routes={"next": "invoices"}),
            _step(
                "invoices",
                "connector",
                {"tool": "stripe.list_invoices", "args": {"status": "open", "limit": 100}},
                {"ok": "plan", "denied": "failed", "error": "failed"},
            ),
            _step(
                "plan",
                "agent",
                {
                    "agent": agent,
                    "task": "Plan one short nudge per open invoice. Submit the result in the required shape.",
                    "inputs": {"invoices": "=nodes.invoices.output", "as_of": "=input.as_of"},
                },
                {"next": "check"},
            ),
            _step(
                "check",
                "decision",
                routes={"nothing": "nothing", "review": "review"},
                rules=DecisionRules(
                    question="Is there anything to nudge?",
                    rules=[
                        DecisionRule(
                            when="size(nodes.plan.output.messages) == 0",
                            route="nothing",
                            explanation="No invoice needs a nudge.",
                        )
                    ],
                    default=DecisionDefault(
                        route="review", explanation="A person checks the planned nudges first."
                    ),
                ),
            ),
            _step(
                "review",
                "human_workforce",
                {
                    "title": "Check the planned nudges",
                    "instructions": "Check each invoice and its planned nudge. Resolve the task when they "
                    "are right.",
                    "show": "=nodes.plan.output.review_items",
                    "timeout_s": 86400,
                },
                {"resolved": "draft", "rejected": "failed", "timeout": "failed"},
            ),
            _step(
                "draft",
                "agent",
                {
                    "agent": "writer-agent",
                    "task": "Write one short, polite email draft per item, using only its facts. Submit the "
                    "result in the required shape.",
                    "inputs": {
                        "items": "=nodes.plan.output.messages",
                        "review": "=nodes.review.output",
                        "tone": "friendly",
                    },
                    "output_schema": "shared/drafts",
                },
                {"next": "approve"},
            ),
            _step(
                "approve",
                "approval",
                {
                    "title": "Save the nudges as drafts",
                    "summary": "='Create ' + string(size(nodes.draft.output.drafts)) + ' email drafts in "
                    "Gmail'",
                    "timeout_s": 86400,
                },
                {"granted": "send", "denied": "failed", "timeout": "failed"},
            ),
            _step(
                "send",
                "connector",
                {
                    "tool": "gmail.create_draft",
                    "for_each": "=nodes.draft.output.drafts",
                    "args": {"recipient_email": "=item.to", "subject": "=item.subject", "body": "=item.body"},
                },
                {"ok": "verify", "denied": "failed", "error": "failed"},
            ),
            _step(
                "verify",
                "verification",
                {
                    "schema": "shared/drafts",
                    "value": "=nodes.draft.output",
                    "checks": ["=size(nodes.send.output.results) == size(nodes.draft.output.drafts)"],
                },
                {"pass": "done", "fail": "failed"},
            ),
            _step("nothing", "end", {"status": "COMPLETED", "deliverable": "=nodes.plan.output"}),
            _step("done", "end", {"status": "COMPLETED", "deliverable": "=nodes.draft.output"}),
            _step("failed", "end", {"status": "FAILED"}),
        ],
    )
