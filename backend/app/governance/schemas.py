from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

GovernanceDomain = Literal["pii", "dedup", "normalizers", "schema_audit", "governance"]
ProposalStatus = Literal["pending_review", "approved", "rejected", "applied", "rolled_back"]
RiskLevel = Literal["low", "medium", "high"]


class ProposalReviewRequest(BaseModel):
    """Reviewer input for approving or rejecting a governance proposal."""

    reviewer: str = Field(default="data-steward", min_length=1, max_length=120)
    notes: str = Field(default="", max_length=1000)


class ProposalApplyRequest(BaseModel):
    """Actor metadata for applying an approved governance proposal."""

    actor: str = Field(default="data-steward", min_length=1, max_length=120)


class ProposalRollbackRequest(BaseModel):
    """Actor and reason for rolling back an applied governance proposal."""

    actor: str = Field(default="data-steward", min_length=1, max_length=120)
    reason: str = Field(default="manual rollback requested", min_length=1, max_length=1000)


class GovernanceProposalResponse(BaseModel):
    """Serialized HITL governance proposal with before/after snapshots."""

    id: str
    domain: str
    action_type: str
    title: str
    summary: str
    status: str
    risk_level: str
    payload: dict[str, Any]
    before_snapshot: Any
    after_snapshot: Any
    created_by: str
    reviewed_by: str | None = None
    review_notes: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None


class AuditEventResponse(BaseModel):
    """Serialized tamper-evident audit log entry."""

    id: str
    sequence_no: int
    domain: str
    action: str
    actor: str
    resource_id: str | None = None
    details: dict[str, Any]
    prev_hash: str
    event_hash: str
    created_at: datetime


class AuditChainVerificationResponse(BaseModel):
    """Result of verifying the SHA-256 hash chain over audit events."""

    valid: bool
    checked_count: int
    broken_at_sequence: int | None = None
    latest_hash: str | None = None
