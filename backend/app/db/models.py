import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class PiiVaultEntry(Base):
    """Encrypted reversible token entry for sensitive PII values."""

    __tablename__ = "pii_vault_entries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    value_hmac: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    policy_name: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GovernanceProposal(Base):
    """Human-in-the-loop approval proposal for high-impact governance changes."""

    __tablename__ = "governance_proposals"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    domain: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
        default="pending_review",
    )
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    before_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Tamper-evident hash-chained audit trail record."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    sequence_no: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
