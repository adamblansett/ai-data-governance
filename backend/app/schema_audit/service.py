from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GovernanceProposal
from app.governance.service import append_audit_event, create_proposal
from app.llm.router import LLMRouter
from app.schema_audit.analyzer import audit_schema, merge_tables, parse_postgres_ddl
from app.schema_audit.schemas import (
    ProposeRemediationRequest,
    SchemaAuditRequest,
    SchemaAuditResponse,
)


async def run_schema_audit(
    session: AsyncSession,
    llm_router: LLMRouter,
    request: SchemaAuditRequest,
) -> SchemaAuditResponse:
    """Profile PostgreSQL DDL and catalog metadata, returning findings and guidance."""
    ddl_tables = parse_postgres_ddl(request.ddl_sql) if request.ddl_sql else []
    merged_tables = merge_tables(ddl_tables, request.tables)
    findings, health_score = audit_schema(
        merged_tables,
        default_retention_days=request.default_retention_days,
    )

    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    llm_prompt = (
        f"Audited {len(merged_tables)} PostgreSQL tables; health score {health_score}/100 with "
        f"{len(findings)} hygiene findings ({by_severity})."
    )
    llm_result = await llm_router.generate(llm_prompt, task_hint="schema_audit")

    await append_audit_event(
        session,
        domain="schema_audit",
        action="schema_audit.analyze",
        actor="schema-auditor",
        details={
            "tables_analyzed": len(merged_tables),
            "health_score": health_score,
            "findings_count": len(findings),
            "findings_by_severity": by_severity,
        },
    )

    return SchemaAuditResponse(
        tables_analyzed=len(merged_tables),
        health_score=health_score,
        findings_count=len(findings),
        findings_by_severity=by_severity,
        findings=findings,
        ai_summary=llm_result.text,
        llm_provider=llm_result.provider,
    )


async def propose_remediation(
    session: AsyncSession,
    request: ProposeRemediationRequest,
) -> GovernanceProposal:
    """Create an HITL governance proposal containing SQL remediation statements."""
    statements = [
        {"finding_id": f.finding_id, "table": f.table, "sql": f.remediation_sql.strip()}
        for f in request.findings
        if f.remediation_sql.strip()
    ]
    if not statements:
        raise ValueError("At least one finding must include a non-empty remediation_sql.")

    tables = sorted({f.table for f in request.findings})
    summary = (
        f"Stage {len(statements)} SQL remediation statements across tables: {', '.join(tables)}."
    )

    payload_data: dict[str, object] = {
        "statements": statements,
        "tables": tables,
    }
    if request.connector_id:
        payload_data["connector_id"] = request.connector_id

    return await create_proposal(
        session,
        domain="schema_audit",
        action_type="schema_remediation",
        title=request.title,
        summary=summary,
        risk_level="high",
        payload=payload_data,
        before_snapshot=[f.model_dump() for f in request.findings],
        created_by=request.created_by,
    )
