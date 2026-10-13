"""Operator console: platform service health and incidents (simulated). Declaring an incident degrades the
services it names; resolving the last open incident on a service restores it."""

from app import workspace
from app.auth import CurrentOps, OpsWriter
from app.errors import NOT_AVAILABLE_LIVE, ApiProblem, conflicts
from app.models.ops import (
    DeclareIncidentRequest,
    Incident,
    IncidentStatus,
    IncidentUpdate,
    OpsHealth,
    UpdateIncidentRequest,
)
from app.routers.ops_params import PathId
from app.routing import ApiRouter
from app.store import Store, locked_store, utc_now

router = ApiRouter(prefix="/v1/ops", tags=["ops"])

LIVE_INCIDENTS = "Incidents are not tracked in the live workspace yet."

# investigating -> monitoring -> resolved; resolving straight from investigating is allowed.
NEXT_STATUSES: dict[IncidentStatus, tuple[IncidentStatus, ...]] = {
    "investigating": ("investigating", "monitoring", "resolved"),
    "monitoring": ("monitoring", "resolved"),
    "resolved": (),
}


def find_incident(store: Store, incident_id: str) -> Incident:
    incident = next((i for i in store.incidents if i.id == incident_id), None)
    if incident is None:
        raise ApiProblem(404, "NOT_FOUND", f"No incident {incident_id}.")
    return incident


def refuse_live_incident_writes() -> None:
    """Incidents are fixtures; the live workspace refuses to change them (no store change, no audit)."""
    if workspace.live():
        raise ApiProblem(409, NOT_AVAILABLE_LIVE, LIVE_INCIDENTS)


@router.get("/health", operation_id="opsGetHealth", response_model=OpsHealth)
def ops_get_health(_: CurrentOps) -> OpsHealth:
    with locked_store() as store:
        incidents = sorted(store.incidents, key=lambda i: i.started_at, reverse=True)
        return OpsHealth(
            services=[s.model_copy() for s in store.services.values()],
            incidents=[i.model_copy(deep=True) for i in incidents],
        )


@router.post(
    "/incidents",
    operation_id="opsDeclareIncident",
    responses=conflicts(NOT_AVAILABLE_LIVE),
    response_model=Incident,
    status_code=201,
)
def ops_declare_incident(body: DeclareIncidentRequest, actor: OpsWriter) -> Incident:
    refuse_live_incident_writes()
    services = list(dict.fromkeys(body.services))
    with locked_store() as store:
        unknown = [key for key in services if key not in store.services]
        if unknown:
            raise ApiProblem(422, "SCHEMA_INVALID", f"Unknown service: {', '.join(unknown)}.")
        now = utc_now()
        incident = Incident(
            id=f"inc_{store.next_incident:04d}",
            title=body.title,
            severity=body.severity,
            status="investigating",
            started_at=now,
            services=services,
            updates=[IncidentUpdate(at=now, by=actor.email, text=body.reason)],
        )
        store.next_incident += 1
        store.incidents.append(incident)
        for key in services:
            if store.services[key].status == "operational":
                store.services[key].status = "degraded"
        store.audit(
            actor,
            "incident.declare",
            "incident",
            incident.id,
            body.reason,
            f"Declared {incident.severity}: {incident.title}",
        )
        return incident.model_copy(deep=True)


@router.post(
    "/incidents/{incident_id}:update",
    operation_id="opsUpdateIncident",
    responses=conflicts(NOT_AVAILABLE_LIVE, "INCIDENT_RESOLVED", "INVALID_TRANSITION"),
    response_model=Incident,
)
def ops_update_incident(incident_id: PathId, body: UpdateIncidentRequest, actor: OpsWriter) -> Incident:
    refuse_live_incident_writes()
    with locked_store() as store:
        incident = find_incident(store, incident_id)
        before = incident.status
        if before == "resolved":
            raise ApiProblem(409, "INCIDENT_RESOLVED", f"{incident.id} is resolved and cannot be updated.")
        if body.status not in NEXT_STATUSES[before]:
            raise ApiProblem(
                409, "INVALID_TRANSITION", f"An incident cannot go from {before} to {body.status}."
            )
        now = utc_now()
        incident.status = body.status
        incident.updates.append(IncidentUpdate(at=now, by=actor.email, text=body.text))
        if body.status == "resolved":
            incident.resolved_at = now
            still_open = {s for i in store.incidents if i.status != "resolved" for s in i.services}
            for key in incident.services:
                if key not in still_open and key in store.services:
                    store.services[key].status = "operational"
                    store.services[key].note = None
        store.audit(
            actor,
            "incident.update",
            "incident",
            incident.id,
            body.reason,
            f"Status {before} → {body.status}",
        )
        return incident.model_copy(deep=True)
