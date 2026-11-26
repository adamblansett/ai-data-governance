from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

JobType = Literal["pii_scan", "schema_audit", "dedup_analyze", "normalizer_preview"]
JobMode = Literal["inline", "background"]


class JobSubmitRequest(BaseModel):
    """Request to run a governance scan/audit inline or asynchronously."""

    job_type: JobType
    execution_mode: JobMode | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class BackgroundJobResponse(BaseModel):
    """Serialized status and result of a tracked governance job."""

    id: str
    job_type: str
    status: str
    execution_mode: str
    created_by: str
    params: dict[str, Any]
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
