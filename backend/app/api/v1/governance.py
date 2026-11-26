from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.crypto import DsnCipher
from app.core.config import Settings
from app.core.security import Principal, require_role, resolve_actor
from app.db.session import get_app_settings, get_db_session
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


def _get_cipher(request: Request, settings: Settings) -> DsnCipher:
    cipher = getattr(request.app.state, "dsn_cipher", None)
    if isinstance(cipher, DsnCipher):
        return cipher
    cipher = DsnCipher(settings)
    request.app.state.dsn_cipher = cipher
    return cipher


@router.get("/proposals", response_model=list[GovernanceProposalResponse])
async def get_proposals(
    domain: str | None = Query(default=None),
    proposal_status: str | None = Query(default=None, alias="status"),
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[GovernanceProposalResponse]:
    """List HITL governance proposals, optionally filtered by domain and status."""
    proposals = await list_proposals(session, domain=domain, status=proposal_status)
    return [serialize_proposal(item) for item in proposals]


@router.get("/proposals/{proposal_id}", response_model=GovernanceProposalResponse)
async def get_single_proposal(
    proposal_id: str,
    _: Principal = Depends(require_role("viewer")),
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
    principal: Principal = Depends(require_role("steward")),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Approve a pending_review governance proposal (steward+, enforces four-eyes)."""
    reviewer = resolve_actor(principal, body.reviewer)
    try:
        proposal = await approve_proposal(
            session,
            proposal_id,
            reviewer=reviewer,
            notes=body.notes,
            enforce_four_eyes=settings.enforce_four_eyes,
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
    principal: Principal = Depends(require_role("steward")),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Reject a pending_review governance proposal (steward+)."""
    reviewer = resolve_actor(principal, body.reviewer)
    try:
        proposal = await reject_proposal(
            session,
            proposal_id,
            reviewer=reviewer,
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
    request: Request,
    principal: Principal = Depends(require_role("steward")),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Apply an approved governance proposal (steward+, enforces HITL approval first)."""
    actor = resolve_actor(principal, body.actor)
    cipher = _get_cipher(request, settings)
    try:
        proposal = await apply_proposal(session, proposal_id, actor=actor, dsn_cipher=cipher)
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ProposalStateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/rollback", response_model=GovernanceProposalResponse)
async def rollback_single_proposal(
    proposal_id: str,
    body: ProposalRollbackRequest,
    request: Request,
    principal: Principal = Depends(require_role("steward")),
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Roll back an applied proposal, restoring snapshots and live connector rows."""
    actor = resolve_actor(principal, body.actor)
    cipher = _get_cipher(request, settings)
    try:
        proposal = await rollback_proposal(
            session,
            proposal_id,
            actor=actor,
            reason=body.reason,
            dsn_cipher=cipher,
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
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEventResponse]:
    """List immutable audit log events ordered newest first."""
    events = await list_audit_events(session, domain=domain, limit=limit)
    return [serialize_audit_event(event) for event in events]


@router.get("/audit/verify", response_model=AuditChainVerificationResponse)
async def verify_audit_log_chain(
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> AuditChainVerificationResponse:
    """Verify integrity of the SHA-256 hash chain over all audit events."""
    return await verify_audit_chain(session)
