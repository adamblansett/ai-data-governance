import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.crypto import DsnCipher
from app.connectors.schemas import (
    ConnectorAuditRequest,
    ConnectorDedupRequest,
    ConnectorPiiScanRequest,
)
from app.connectors.service import (
    audit_connector_schema,
    dedup_connector_table,
    scan_connector_table_pii,
)
from app.db.models import BackgroundJob
from app.db.session import DatabaseManager
from app.dedup.schemas import DedupAnalyzeRequest
from app.dedup.service import analyze_duplicates
from app.governance.service import append_audit_event
from app.jobs.schemas import BackgroundJobResponse, JobMode, JobSubmitRequest
from app.llm.router import LLMRouter
from app.normalizers.schemas import NormalizerPreviewRequest
from app.normalizers.service import preview_normalization
from app.pii.schemas import PiiScanRequest
from app.pii.service import scan_pii
from app.pii.vault import PiiVault
from app.schema_audit.schemas import SchemaAuditRequest
from app.schema_audit.service import run_schema_audit


class JobNotFoundError(Exception):
    """Raised when a background job ID cannot be located."""


def _safe_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def serialize_job(job: BackgroundJob) -> BackgroundJobResponse:
    """Convert ORM BackgroundJob into API response schema."""
    return BackgroundJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        execution_mode=job.execution_mode,
        created_by=job.created_by,
        params=_safe_json(job.params_json, {}),
        result=_safe_json(job.result_json, None),
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


class JobRunner:
    """Executes governance jobs inline or asynchronously in tracked background tasks."""

    def __init__(
        self,
        db: DatabaseManager,
        vault: PiiVault,
        llm_router: LLMRouter,
        dsn_cipher: DsnCipher,
        default_mode: JobMode = "inline",
    ) -> None:
        self.db = db
        self.vault = vault
        self.llm_router = llm_router
        self.dsn_cipher = dsn_cipher
        self.default_mode: JobMode = default_mode
        self._tasks: set[asyncio.Task[None]] = set()

    async def shutdown(self) -> None:
        """Await or cancel any pending background tasks during app shutdown."""
        if not self._tasks:
            return
        pending = list(self._tasks)
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def submit_job(
        self,
        session: AsyncSession,
        request: JobSubmitRequest,
        *,
        created_by: str,
    ) -> BackgroundJob:
        """Create and run (inline or background) a tracked governance job."""
        mode: JobMode = request.execution_mode or self.default_mode
        job = BackgroundJob(
            job_type=request.job_type,
            status="queued",
            execution_mode=mode,
            created_by=created_by,
            params_json=json.dumps(request.params, default=str),
        )
        session.add(job)
        await session.flush()

        if mode == "inline":
            await self._execute_in_session(session, job)
            return job

        # Commit queued record so the detached background task sees it immediately.
        await session.commit()
        await session.refresh(job)

        task = asyncio.create_task(self._run_background(job.id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run_background(self, job_id: str) -> None:
        await self.db.initialize()
        async with self.db.session_factory() as session:
            try:
                res = await session.execute(
                    select(BackgroundJob).where(BackgroundJob.id == job_id)
                )
                job = res.scalar_one_or_none()
                if job is None:
                    return
                await self._execute_in_session(session, job)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _execute_in_session(self, session: AsyncSession, job: BackgroundJob) -> None:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        await session.flush()

        params = _safe_json(job.params_json, {})
        try:
            result_model = await self._dispatch(session, job, params)
            job.result_json = json.dumps(result_model.model_dump(), default=str)
            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            await session.flush()
            await append_audit_event(
                session,
                domain="jobs",
                action="jobs.completed",
                actor=job.created_by,
                resource_id=job.id,
                details={
                    "job_type": job.job_type,
                    "execution_mode": job.execution_mode,
                },
            )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(UTC)
            await session.flush()
            await append_audit_event(
                session,
                domain="jobs",
                action="jobs.failed",
                actor=job.created_by,
                resource_id=job.id,
                details={
                    "job_type": job.job_type,
                    "error": str(exc)[:300],
                },
            )

    async def _dispatch(
        self,
        session: AsyncSession,
        job: BackgroundJob,
        params: dict[str, Any],
    ) -> Any:
        connector_id = params.get("connector_id")
        table_name = params.get("table_name")

        if job.job_type == "pii_scan":
            if connector_id and table_name:
                return await scan_connector_table_pii(
                    session,
                    self.dsn_cipher,
                    str(connector_id),
                    str(table_name),
                    ConnectorPiiScanRequest(
                        limit=int(params.get("limit", 100)),
                        policy_name=str(params.get("policy_name", "default")),
                        include_ner=bool(params.get("include_ner", True)),
                    ),
                )
            return await scan_pii(session, PiiScanRequest(**params))

        if job.job_type == "schema_audit":
            if connector_id:
                return await audit_connector_schema(
                    session,
                    self.dsn_cipher,
                    self.llm_router,
                    str(connector_id),
                    ConnectorAuditRequest(
                        default_retention_days=int(params.get("default_retention_days", 365))
                    ),
                    actor=job.created_by,
                )
            return await run_schema_audit(session, self.llm_router, SchemaAuditRequest(**params))

        if job.job_type == "dedup_analyze":
            if connector_id and table_name:
                return await dedup_connector_table(
                    session,
                    self.dsn_cipher,
                    self.llm_router,
                    str(connector_id),
                    str(table_name),
                    ConnectorDedupRequest(
                        limit=int(params.get("limit", 100)),
                        id_field=str(params.get("id_field", "id")),
                        threshold=float(params.get("threshold", 0.78)),
                        survivorship=params.get("survivorship", "most_complete"),
                    ),
                )
            return await analyze_duplicates(session, self.llm_router, DedupAnalyzeRequest(**params))

        if job.job_type == "normalizer_preview":
            return await preview_normalization(session, NormalizerPreviewRequest(**params))

        raise ValueError(f"Unsupported job type '{job.job_type}'.")


async def list_jobs(session: AsyncSession, *, limit: int = 50) -> list[BackgroundJob]:
    """List background jobs ordered newest first."""
    res = await session.execute(
        select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
    )
    return list(res.scalars().all())


async def get_job(session: AsyncSession, job_id: str) -> BackgroundJob:
    """Retrieve a single job by ID or raise JobNotFoundError."""
    res = await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))
    job = res.scalar_one_or_none()
    if job is None:
        raise JobNotFoundError(f"Job '{job_id}' not found.")
    return job
