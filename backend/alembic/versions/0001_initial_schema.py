"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-26 07:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pii_vault_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("value_hmac", sa.String(length=64), nullable=False),
        sa.Column("policy_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pii_vault_entries_token", "pii_vault_entries", ["token"], unique=True)
    op.create_index(
        "ix_pii_vault_entries_entity_type", "pii_vault_entries", ["entity_type"], unique=False
    )
    op.create_index(
        "ix_pii_vault_entries_value_hmac", "pii_vault_entries", ["value_hmac"], unique=False
    )

    op.create_table(
        "governance_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("before_snapshot_json", sa.Text(), nullable=False),
        sa.Column("after_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("reviewed_by", sa.String(length=120), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_governance_proposals_domain", "governance_proposals", ["domain"], unique=False
    )
    op.create_index(
        "ix_governance_proposals_status", "governance_proposals", ["status"], unique=False
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_sequence_no", "audit_events", ["sequence_no"], unique=True)
    op.create_index("ix_audit_events_domain", "audit_events", ["domain"], unique=False)
    op.create_index("ix_audit_events_action", "audit_events", ["action"], unique=False)

    op.create_table(
        "data_connectors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("connector_type", sa.String(length=32), nullable=False),
        sa.Column("dsn_encrypted", sa.Text(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_connectors_name", "data_connectors", ["name"], unique=True)

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_background_jobs_job_type", "background_jobs", ["job_type"], unique=False)
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_job_type", table_name="background_jobs")
    op.drop_table("background_jobs")

    op.drop_index("ix_data_connectors_name", table_name="data_connectors")
    op.drop_table("data_connectors")

    op.drop_index("ix_audit_events_action", table_name="audit_events")
    op.drop_index("ix_audit_events_domain", table_name="audit_events")
    op.drop_index("ix_audit_events_sequence_no", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_governance_proposals_status", table_name="governance_proposals")
    op.drop_index("ix_governance_proposals_domain", table_name="governance_proposals")
    op.drop_table("governance_proposals")

    op.drop_index("ix_pii_vault_entries_value_hmac", table_name="pii_vault_entries")
    op.drop_index("ix_pii_vault_entries_entity_type", table_name="pii_vault_entries")
    op.drop_index("ix_pii_vault_entries_token", table_name="pii_vault_entries")
    op.drop_table("pii_vault_entries")
