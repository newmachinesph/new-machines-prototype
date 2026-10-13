"""Operator console: one real run with its work receipt. (The cross-tenant list is in ops_people.)"""

from app import real_runs, settings
from app.auth import CurrentOps
from app.errors import ApiProblem
from app.models.ops import OpsRunDetail
from app.routers.ops_params import PathId
from app.routing import ApiRouter

router = ApiRouter(prefix="/v1/ops", tags=["ops"])


@router.get("/runs/{run_id}", operation_id="opsGetRun", response_model=OpsRunDetail)
def ops_get_run(run_id: PathId, _: CurrentOps) -> OpsRunDetail:
    """A real run (any tenant) with its receipt, the hash chain verified now. 404 for fixture runs."""
    run = real_runs.ops_run(run_id) if settings.runtime_enabled() else None
    found = real_runs.receipt_of(None, run_id) if run else None
    if run is None or found is None:
        raise ApiProblem(404, "NOT_FOUND", f"No real run {run_id}. Only real runs have a receipt.")
    return OpsRunDetail(run=run, receipt=found)
