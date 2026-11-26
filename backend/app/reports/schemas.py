from datetime import datetime

from pydantic import BaseModel

from app.governance.schemas import AuditChainVerificationResponse, AuditEventResponse


class ComplianceReportResponse(BaseModel):
    """Aggregated governance posture, vault summary, and SHA-256 chain proof."""

    generated_at: datetime
    vault_total_tokens: int
    vault_by_entity_type: dict[str, int]
    proposals_total: int
    proposals_by_status: dict[str, int]
    proposals_by_domain: dict[str, int]
    connectors_total: int
    jobs_total: int
    jobs_by_status: dict[str, int]
    audit_chain: AuditChainVerificationResponse
    recent_audit_events: list[AuditEventResponse]
