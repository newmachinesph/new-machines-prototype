from fastapi import Response

from app.auth import Actor, CurrentActor
from app.errors import ApiProblem
from app.models.common import Model
from app.models.org import AttentionItem, LedgerTxn, McpToken, Member, Organization, Policy
from app.models.requests import CreatedToken, CreateTokenRequest, InviteRequest
from app.routing import ApiRouter
from app.store import Store, get_store, locked_store

router = ApiRouter(prefix="/v1", tags=["organization"])


class Usage(Model):
    org: Organization
    ledger: list[LedgerTxn]


def require_org(org_id: str, actor: Actor) -> Organization:
    if org_id != actor.org_id:
        raise ApiProblem(403, "TENANT_SCOPE_DENIED", "You are not a member of that workspace.")
    return get_store().org


@router.get("/organizations/{org_id}", operation_id="getOrganization", response_model=Organization)
def get_organization(org_id: str, actor: CurrentActor) -> Organization:
    return require_org(org_id, actor)


@router.get("/organizations/{org_id}/policies", operation_id="listPolicies", response_model=list[Policy])
def list_policies(org_id: str, actor: CurrentActor) -> list[Policy]:
    require_org(org_id, actor)
    return get_store().policies


@router.get("/organizations/{org_id}/members", operation_id="listMembers", response_model=list[Member])
def list_members(org_id: str, actor: CurrentActor) -> list[Member]:
    require_org(org_id, actor)
    return get_store().members


@router.get("/organizations/{org_id}/usage", operation_id="getUsage", response_model=Usage)
def get_usage(org_id: str, actor: CurrentActor) -> Usage:
    org = require_org(org_id, actor)
    return Usage(org=org, ledger=get_store().ledger)


@router.get(
    "/organizations/{org_id}/attention", operation_id="listAttention", response_model=list[AttentionItem]
)
def list_attention(org_id: str, actor: CurrentActor) -> list[AttentionItem]:
    require_org(org_id, actor)
    with locked_store() as store:
        return live_attention(store)


# The approval and memory-candidate items are derived from live state; the fixture's versions of them are
# only the starting picture, so they are dropped in favour of the derived ones.
LIVE_HREFS = {"/app/approvals", "/app/memory"}


def live_attention(store: Store) -> list[AttentionItem]:
    items = [item for item in store.attention if item.href not in LIVE_HREFS]
    pending = [a for a in store.approvals if a.status == "PENDING"]
    if pending:
        n = len(pending)
        items.append(
            AttentionItem(
                actor="buyer",
                title="Approve one outgoing email" if n == 1 else f"Approve {n} outgoing emails",
                detail=pending[0].title,
                href="/app/approvals",
                when=max(a.requested_at for a in pending),
            )
        )
    candidates = [m for m in store.memory if m.state == "CANDIDATE"]
    if candidates:
        n = len(candidates)
        items.append(
            AttentionItem(
                actor="human",
                title="Approve a memory from a reviewer" if n == 1 else f"Review {n} proposed memories",
                detail=candidates[0].text,
                href="/app/memory",
                when=max(m.created_at for m in candidates),
            )
        )
    return sorted(items, key=lambda item: item.when, reverse=True)


@router.get("/tokens", operation_id="listTokens", response_model=list[McpToken])
def list_tokens(_: CurrentActor) -> list[McpToken]:
    return get_store().tokens


@router.post(
    "/organizations/{org_id}/invitations", operation_id="inviteMember", response_model=Member, status_code=201
)
def invite_member(org_id: str, body: InviteRequest, actor: CurrentActor) -> Member:
    require_org(org_id, actor)
    with locked_store() as store:
        if any(m.email.lower() == body.email.lower() for m in store.members):
            raise ApiProblem(409, "CONFLICT", "This person is already in the workspace or invited.")
        member = Member(name=body.email, email=body.email, role=body.role, via="Invite link", pending=True)
        store.members.append(member)
        return member


@router.post("/tokens", operation_id="createToken", response_model=CreatedToken, status_code=201)
def create_token(body: CreateTokenRequest, _: CurrentActor) -> CreatedToken:
    with locked_store() as store:
        token = McpToken(
            id=f"pat_demo_{store.next_token}",
            name=body.name,
            last4="DEMO",
            scopes=list(body.scopes),
            created_at="2026-10-12T16:40:00Z",
            expires_at="2026-11-11T16:40:00Z",
            last_used="",
        )
        store.next_token += 1
        store.tokens.append(token)
    return CreatedToken(token=token, secret=f"nm_pat_demo_{token.id}_not_a_real_token")


@router.delete("/tokens/{token_id}", operation_id="revokeToken", status_code=204, response_class=Response)
def revoke_token(token_id: str, _: CurrentActor) -> Response:
    with locked_store() as store:
        if not any(t.id == token_id for t in store.tokens):
            raise ApiProblem(404, "NOT_FOUND", f"No token {token_id}.")
        store.tokens = [t for t in store.tokens if t.id != token_id]
    return Response(status_code=204)
