from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.governance.schemas import (
    AuditChainVerificationResponse,
    AuditEventResponse,
    GovernanceProposalResponse,
    ProposalApplyRequest,
    ProposalReviewRequest,
    ProposalRollbackRequest,
)
from app.governance.service import (
    ProposalNotFoundError,
    ProposalStateError,
    apply_proposal,
    approve_proposal,
    get_proposal,
    list_audit_events,
    list_proposals,
    reject_proposal,
    rollback_proposal,
    serialize_audit_event,
    serialize_proposal,
    verify_audit_chain,
)

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/proposals", response_model=list[GovernanceProposalResponse])
async def get_proposals(
    domain: str | None = Query(default=None),
    proposal_status: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_db_session),
) -> list[GovernanceProposalResponse]:
    """List HITL governance proposals, optionally filtered by domain and status."""
    proposals = await list_proposals(session, domain=domain, status=proposal_status)
    return [serialize_proposal(item) for item in proposals]


@router.get("/proposals/{proposal_id}", response_model=GovernanceProposalResponse)
async def get_single_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Retrieve a single governance proposal by ID."""
    try:
        proposal = await get_proposal(session, proposal_id)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=GovernanceProposalResponse)
async def approve_single_proposal(
    proposal_id: str,
    body: ProposalReviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Approve a pending_review governance proposal."""
    try:
        proposal = await approve_proposal(
            session,
            proposal_id,
            reviewer=body.reviewer,
            notes=body.notes,
        )
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/reject", response_model=GovernanceProposalResponse)
async def reject_single_proposal(
    proposal_id: str,
    body: ProposalReviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Reject a pending_review governance proposal."""
    try:
        proposal = await reject_proposal(
            session,
            proposal_id,
            reviewer=body.reviewer,
            notes=body.notes,
        )
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/apply", response_model=GovernanceProposalResponse)
async def apply_single_proposal(
    proposal_id: str,
    body: ProposalApplyRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Apply an approved governance proposal (enforces HITL approval first)."""
    try:
        proposal = await apply_proposal(session, proposal_id, actor=body.actor)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/rollback", response_model=GovernanceProposalResponse)
async def rollback_single_proposal(
    proposal_id: str,
    body: ProposalRollbackRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Roll back an applied proposal, restoring visibility to its before-snapshot."""
    try:
        proposal = await rollback_proposal(
            session,
            proposal_id,
            actor=body.actor,
            reason=body.reason,
        )
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.get("/audit", response_model=list[AuditEventResponse])
async def get_audit_trail(
    domain: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEventResponse]:
    """List immutable audit log events ordered newest first."""
    events = await list_audit_events(session, domain=domain, limit=limit)
    return [serialize_audit_event(event) for event in events]


@router.get("/audit/verify", response_model=AuditChainVerificationResponse)
async def verify_audit_log_chain(
    session: AsyncSession = Depends(get_db_session),
) -> AuditChainVerificationResponse:
    """Verify integrity of the SHA-256 hash chain over all audit events."""
    return await verify_audit_chain(session)
