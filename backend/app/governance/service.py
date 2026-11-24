import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, GovernanceProposal
from app.governance.schemas import (
    AuditChainVerificationResponse,
    AuditEventResponse,
    GovernanceProposalResponse,
)

GENESIS_HASH = "0" * 64


class ProposalNotFoundError(Exception):
    """Raised when a governance proposal ID cannot be located."""


class ProposalStateError(Exception):
    """Raised when a proposal transition violates the HITL approval state machine."""


def normalize_utc_iso(dt: datetime) -> str:
    """Normalize a datetime to UTC ISO-8601 string for deterministic hashing."""
    normalized = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return normalized.isoformat()


def compute_event_hash(
    sequence_no: int,
    domain: str,
    action: str,
    actor: str,
    resource_id: str | None,
    details_json: str,
    created_at_iso: str,
    prev_hash: str,
) -> str:
    """Compute SHA-256 hash linking an audit event to the previous hash."""
    canonical = "|".join(
        [
            str(sequence_no),
            domain,
            action,
            actor,
            resource_id or "",
            details_json,
            created_at_iso,
            prev_hash,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def append_audit_event(
    session: AsyncSession,
    *,
    domain: str,
    action: str,
    actor: str = "system",
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append an immutable, hash-chained audit event (must never contain raw PII)."""
    result = await session.execute(
        select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(1)
    )
    last_event = result.scalar_one_or_none()

    sequence_no = (last_event.sequence_no + 1) if last_event is not None else 1
    prev_hash = last_event.event_hash if last_event is not None else GENESIS_HASH
    created_at = datetime.now(UTC)
    details_json = json.dumps(details or {}, sort_keys=True, default=str)
    event_hash = compute_event_hash(
        sequence_no=sequence_no,
        domain=domain,
        action=action,
        actor=actor,
        resource_id=resource_id,
        details_json=details_json,
        created_at_iso=normalize_utc_iso(created_at),
        prev_hash=prev_hash,
    )

    event = AuditEvent(
        sequence_no=sequence_no,
        domain=domain,
        action=action,
        actor=actor,
        resource_id=resource_id,
        details_json=details_json,
        prev_hash=prev_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    session.add(event)
    await session.flush()
    return event


async def verify_audit_chain(session: AsyncSession) -> AuditChainVerificationResponse:
    """Verify monotonic sequence numbers, prev_hash links, and SHA-256 digests."""
    result = await session.execute(select(AuditEvent).order_by(AuditEvent.sequence_no.asc()))
    events = list(result.scalars().all())
    if not events:
        return AuditChainVerificationResponse(
            valid=True,
            checked_count=0,
            broken_at_sequence=None,
            latest_hash=None,
        )

    expected_prev_hash = GENESIS_HASH
    expected_sequence = 1
    latest_hash: str | None = None

    for event in events:
        if event.sequence_no != expected_sequence or event.prev_hash != expected_prev_hash:
            return AuditChainVerificationResponse(
                valid=False,
                checked_count=expected_sequence - 1,
                broken_at_sequence=event.sequence_no,
                latest_hash=latest_hash,
            )

        recomputed = compute_event_hash(
            sequence_no=event.sequence_no,
            domain=event.domain,
            action=event.action,
            actor=event.actor,
            resource_id=event.resource_id,
            details_json=event.details_json,
            created_at_iso=normalize_utc_iso(event.created_at),
            prev_hash=event.prev_hash,
        )
        if event.event_hash != recomputed:
            return AuditChainVerificationResponse(
                valid=False,
                checked_count=expected_sequence - 1,
                broken_at_sequence=event.sequence_no,
                latest_hash=latest_hash,
            )

        expected_prev_hash = event.event_hash
        latest_hash = event.event_hash
        expected_sequence += 1

    return AuditChainVerificationResponse(
        valid=True,
        checked_count=len(events),
        broken_at_sequence=None,
        latest_hash=latest_hash,
    )


def _safe_json_loads(raw: str, default: Any) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def serialize_proposal(proposal: GovernanceProposal) -> GovernanceProposalResponse:
    """Convert ORM GovernanceProposal into API response schema."""
    return GovernanceProposalResponse(
        id=proposal.id,
        domain=proposal.domain,
        action_type=proposal.action_type,
        title=proposal.title,
        summary=proposal.summary,
        status=proposal.status,
        risk_level=proposal.risk_level,
        payload=_safe_json_loads(proposal.payload_json, {}),
        before_snapshot=_safe_json_loads(proposal.before_snapshot_json, {}),
        after_snapshot=_safe_json_loads(proposal.after_snapshot_json, {}),
        created_by=proposal.created_by,
        reviewed_by=proposal.reviewed_by,
        review_notes=proposal.review_notes,
        created_at=proposal.created_at,
        reviewed_at=proposal.reviewed_at,
        applied_at=proposal.applied_at,
        rolled_back_at=proposal.rolled_back_at,
    )


def serialize_audit_event(event: AuditEvent) -> AuditEventResponse:
    """Convert ORM AuditEvent into API response schema."""
    return AuditEventResponse(
        id=event.id,
        sequence_no=event.sequence_no,
        domain=event.domain,
        action=event.action,
        actor=event.actor,
        resource_id=event.resource_id,
        details=_safe_json_loads(event.details_json, {}),
        prev_hash=event.prev_hash,
        event_hash=event.event_hash,
        created_at=event.created_at,
    )


async def _load_proposal(session: AsyncSession, proposal_id: str) -> GovernanceProposal:
    result = await session.execute(
        select(GovernanceProposal).where(GovernanceProposal.id == proposal_id)
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise ProposalNotFoundError(f"Proposal '{proposal_id}' not found.")
    return proposal


async def create_proposal(
    session: AsyncSession,
    *,
    domain: str,
    action_type: str,
    title: str,
    summary: str,
    risk_level: str,
    payload: dict[str, Any],
    before_snapshot: Any,
    created_by: str = "governance-agent",
) -> GovernanceProposal:
    """Create a pending_review HITL proposal and append an audit event."""
    proposal = GovernanceProposal(
        domain=domain,
        action_type=action_type,
        title=title,
        summary=summary,
        status="pending_review",
        risk_level=risk_level,
        payload_json=json.dumps(payload, default=str),
        before_snapshot_json=json.dumps(before_snapshot, default=str),
        after_snapshot_json="{}",
        created_by=created_by,
    )
    session.add(proposal)
    await session.flush()

    await append_audit_event(
        session,
        domain=domain,
        action="proposal.created",
        actor=created_by,
        resource_id=proposal.id,
        details={
            "action_type": action_type,
            "risk_level": risk_level,
            "title": title,
        },
    )
    return proposal


async def list_proposals(
    session: AsyncSession,
    *,
    domain: str | None = None,
    status: str | None = None,
) -> list[GovernanceProposal]:
    """Return proposals ordered newest first, optionally filtered by domain and status."""
    stmt = select(GovernanceProposal).order_by(GovernanceProposal.created_at.desc())
    if domain:
        stmt = stmt.where(GovernanceProposal.domain == domain)
    if status:
        stmt = stmt.where(GovernanceProposal.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_proposal(session: AsyncSession, proposal_id: str) -> GovernanceProposal:
    """Return a single proposal by ID or raise ProposalNotFoundError."""
    return await _load_proposal(session, proposal_id)


async def approve_proposal(
    session: AsyncSession,
    proposal_id: str,
    *,
    reviewer: str,
    notes: str = "",
) -> GovernanceProposal:
    """Transition a pending_review proposal to approved."""
    proposal = await _load_proposal(session, proposal_id)
    if proposal.status != "pending_review":
        raise ProposalStateError(
            f"Cannot approve proposal in state '{proposal.status}'; expected 'pending_review'."
        )

    proposal.status = "approved"
    proposal.reviewed_by = reviewer
    proposal.review_notes = notes or None
    proposal.reviewed_at = datetime.now(UTC)
    await session.flush()

    await append_audit_event(
        session,
        domain=proposal.domain,
        action="proposal.approved",
        actor=reviewer,
        resource_id=proposal.id,
        details={"action_type": proposal.action_type, "notes": notes},
    )
    return proposal


async def reject_proposal(
    session: AsyncSession,
    proposal_id: str,
    *,
    reviewer: str,
    notes: str = "",
) -> GovernanceProposal:
    """Transition a pending_review proposal to rejected."""
    proposal = await _load_proposal(session, proposal_id)
    if proposal.status != "pending_review":
        raise ProposalStateError(
            f"Cannot reject proposal in state '{proposal.status}'; expected 'pending_review'."
        )

    proposal.status = "rejected"
    proposal.reviewed_by = reviewer
    proposal.review_notes = notes or None
    proposal.reviewed_at = datetime.now(UTC)
    await session.flush()

    await append_audit_event(
        session,
        domain=proposal.domain,
        action="proposal.rejected",
        actor=reviewer,
        resource_id=proposal.id,
        details={"action_type": proposal.action_type, "notes": notes},
    )
    return proposal


def _build_after_snapshot(
    proposal: GovernanceProposal,
    payload: dict[str, Any],
    actor: str,
    applied_at: datetime,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "applied_action": proposal.action_type,
        "applied_by": actor,
        "applied_at": normalize_utc_iso(applied_at),
    }
    if "golden_record" in payload:
        base["golden_record"] = payload["golden_record"]
        base["merged_record_ids"] = payload.get("record_ids", [])
        return base
    if "normalized_records" in payload:
        base["records"] = payload["normalized_records"]
        base["changes_count"] = payload.get("changes_count", 0)
        return base
    if "statements" in payload:
        base["statements"] = payload["statements"]
        return base
    base["payload"] = payload
    return base


async def apply_proposal(
    session: AsyncSession,
    proposal_id: str,
    *,
    actor: str,
) -> GovernanceProposal:
    """Apply an approved HITL proposal and compute its after-state snapshot."""
    proposal = await _load_proposal(session, proposal_id)
    if proposal.status != "approved":
        raise ProposalStateError(
            f"Cannot apply proposal in state '{proposal.status}'; human approval is required first."
        )

    applied_at = datetime.now(UTC)
    payload = _safe_json_loads(proposal.payload_json, {})
    after_snapshot = _build_after_snapshot(proposal, payload, actor, applied_at)

    proposal.after_snapshot_json = json.dumps(after_snapshot, default=str)
    proposal.status = "applied"
    proposal.applied_at = applied_at
    await session.flush()

    await append_audit_event(
        session,
        domain=proposal.domain,
        action="proposal.applied",
        actor=actor,
        resource_id=proposal.id,
        details={"action_type": proposal.action_type},
    )
    return proposal


async def rollback_proposal(
    session: AsyncSession,
    proposal_id: str,
    *,
    actor: str,
    reason: str,
) -> GovernanceProposal:
    """Roll back an applied proposal while preserving the original before snapshot."""
    proposal = await _load_proposal(session, proposal_id)
    if proposal.status != "applied":
        raise ProposalStateError(
            f"Cannot rollback proposal in state '{proposal.status}'; expected 'applied'."
        )

    proposal.status = "rolled_back"
    proposal.rolled_back_at = datetime.now(UTC)
    await session.flush()

    await append_audit_event(
        session,
        domain=proposal.domain,
        action="proposal.rolled_back",
        actor=actor,
        resource_id=proposal.id,
        details={
            "action_type": proposal.action_type,
            "reason": reason,
            "restored_from_before_snapshot": True,
        },
    )
    return proposal


async def list_audit_events(
    session: AsyncSession,
    *,
    domain: str | None = None,
    limit: int = 100,
) -> list[AuditEvent]:
    """Return audit events ordered by sequence_no descending."""
    stmt = select(AuditEvent).order_by(AuditEvent.sequence_no.desc()).limit(limit)
    if domain:
        stmt = stmt.where(AuditEvent.domain == domain)
    result = await session.execute(stmt)
    return list(result.scalars().all())
