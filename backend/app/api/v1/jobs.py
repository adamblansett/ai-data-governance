from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.crypto import DsnCipher
from app.core.security import Principal, require_role
from app.db.session import get_app_settings, get_db_manager, get_db_session
from app.jobs.runner import JobNotFoundError, JobRunner, get_job, list_jobs, serialize_job
from app.jobs.schemas import BackgroundJobResponse, JobSubmitRequest
from app.llm.router import LLMRouter
from app.pii.vault import PiiVault

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _get_job_runner(request: Request) -> JobRunner:
    runner = getattr(request.app.state, "job_runner", None)
    if isinstance(runner, JobRunner):
        return runner
    settings = get_app_settings(request)
    db = get_db_manager(request)
    vault = getattr(request.app.state, "pii_vault", None)
    if not isinstance(vault, PiiVault):
        vault = PiiVault(settings)
        request.app.state.pii_vault = vault
    llm_router = getattr(request.app.state, "llm_router", None)
    if not isinstance(llm_router, LLMRouter):
        llm_router = LLMRouter(settings)
        request.app.state.llm_router = llm_router
    cipher = getattr(request.app.state, "dsn_cipher", None)
    if not isinstance(cipher, DsnCipher):
        cipher = DsnCipher(settings)
        request.app.state.dsn_cipher = cipher
    runner = JobRunner(
        db=db,
        vault=vault,
        llm_router=llm_router,
        dsn_cipher=cipher,
        default_mode=settings.task_execution_mode,
    )
    request.app.state.job_runner = runner
    return runner


@router.post("/submit", response_model=BackgroundJobResponse)
async def submit_job_endpoint(
    payload: JobSubmitRequest,
    request: Request,
    principal: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> BackgroundJobResponse:
    """Submit an inline or asynchronous background governance job."""
    runner = _get_job_runner(request)
    job = await runner.submit_job(session, payload, created_by=principal.sub)
    return serialize_job(job)


@router.get("", response_model=list[BackgroundJobResponse])
async def list_jobs_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[BackgroundJobResponse]:
    """List submitted governance jobs ordered newest first."""
    jobs = await list_jobs(session, limit=limit)
    return [serialize_job(item) for item in jobs]


@router.get("/{job_id}", response_model=BackgroundJobResponse)
async def get_job_endpoint(
    job_id: str,
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> BackgroundJobResponse:
    """Retrieve a single job's status and serialized result."""
    try:
        job = await get_job(session, job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return serialize_job(job)
