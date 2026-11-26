from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.crypto import DsnCipher, normalize_async_dsn, redact_dsn
from app.connectors.inspector import introspect_tables, sample_table_rows, test_connection
from app.connectors.schemas import (
    ConnectorAuditRequest,
    ConnectorCreateRequest,
    ConnectorDedupRequest,
    ConnectorPiiScanRequest,
    ConnectorResponse,
    ConnectorSampleResponse,
    ConnectorTestResponse,
)
from app.db.models import DataConnector
from app.dedup.schemas import DedupAnalyzeRequest, DedupAnalyzeResponse
from app.dedup.service import analyze_duplicates
from app.governance.service import append_audit_event
from app.llm.router import LLMRouter
from app.pii.schemas import PiiScanRequest, PiiScanResponse
from app.pii.service import scan_pii
from app.schema_audit.analyzer import audit_schema
from app.schema_audit.schemas import SchemaAuditResponse


class ConnectorNotFoundError(Exception):
    """Raised when a requested database connector does not exist."""


class ConnectorConflictError(Exception):
    """Raised when registering a duplicate connector name."""


def serialize_connector(connector: DataConnector, cipher: DsnCipher) -> ConnectorResponse:
    """Serialize ORM DataConnector with masked DSN (never returns plaintext credentials)."""
    try:
        raw_dsn = cipher.decrypt(connector.dsn_encrypted)
        masked = redact_dsn(raw_dsn)
    except Exception:
        masked = "***"
    return ConnectorResponse(
        id=connector.id,
        name=connector.name,
        connector_type=connector.connector_type,
        dsn_masked=masked,
        read_only=connector.read_only,
        description=connector.description,
        created_by=connector.created_by,
        created_at=connector.created_at,
    )


async def _load_connector(session: AsyncSession, connector_id: str) -> DataConnector:
    res = await session.execute(select(DataConnector).where(DataConnector.id == connector_id))
    connector = res.scalar_one_or_none()
    if connector is None:
        raise ConnectorNotFoundError(f"Connector '{connector_id}' not found.")
    return connector


async def create_connector(
    session: AsyncSession,
    cipher: DsnCipher,
    request: ConnectorCreateRequest,
    *,
    created_by: str,
) -> DataConnector:
    """Register a new database connector with HKDF/Fernet-encrypted DSN."""
    existing = await session.execute(
        select(DataConnector).where(DataConnector.name == request.name.strip())
    )
    if existing.scalar_one_or_none() is not None:
        raise ConnectorConflictError(f"Connector named '{request.name}' already exists.")

    normalized_dsn = normalize_async_dsn(request.dsn, request.connector_type)
    connector = DataConnector(
        name=request.name.strip(),
        connector_type=request.connector_type,
        dsn_encrypted=cipher.encrypt(normalized_dsn),
        read_only=request.read_only,
        description=request.description,
        created_by=created_by,
    )
    session.add(connector)
    await session.flush()

    await append_audit_event(
        session,
        domain="connectors",
        action="connector.created",
        actor=created_by,
        resource_id=connector.id,
        details={
            "name": connector.name,
            "connector_type": connector.connector_type,
            "read_only": connector.read_only,
        },
    )
    return connector


async def list_connectors(session: AsyncSession) -> list[DataConnector]:
    """List registered database connectors ordered by creation time."""
    res = await session.execute(select(DataConnector).order_by(DataConnector.created_at.desc()))
    return list(res.scalars().all())


async def delete_connector(
    session: AsyncSession,
    connector_id: str,
    *,
    actor: str,
) -> None:
    """Delete a registered database connector and record an audit event."""
    connector = await _load_connector(session, connector_id)
    name = connector.name
    await session.delete(connector)
    await session.flush()
    await append_audit_event(
        session,
        domain="connectors",
        action="connector.deleted",
        actor=actor,
        resource_id=connector_id,
        details={"name": name},
    )


async def test_connector(
    session: AsyncSession,
    cipher: DsnCipher,
    connector_id: str,
) -> ConnectorTestResponse:
    """Run live SELECT 1 connectivity check against a registered connector."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    ok, dialect, latency_ms, table_count, err = await test_connection(dsn)
    return ConnectorTestResponse(
        connector_id=connector.id,
        name=connector.name,
        connector_type=connector.connector_type,
        ok=ok,
        dialect=dialect,
        latency_ms=latency_ms,
        table_count=table_count,
        error=err,
    )


async def introspect_connector_tables(
    session: AsyncSession,
    cipher: DsnCipher,
    connector_id: str,
) -> list[dict[str, Any]]:
    """Introspect live table metadata from a registered database connector."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    tables = await introspect_tables(dsn)
    return [t.model_dump() for t in tables]


async def sample_connector_table(
    session: AsyncSession,
    cipher: DsnCipher,
    connector_id: str,
    table_name: str,
    *,
    limit: int = 50,
) -> ConnectorSampleResponse:
    """Sample bounded rows from a live connector table."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    columns, rows = await sample_table_rows(dsn, table_name, limit=limit)
    return ConnectorSampleResponse(
        connector_id=connector.id,
        table_name=table_name,
        row_count_sampled=len(rows),
        columns=columns,
        rows=rows,
    )


async def audit_connector_schema(
    session: AsyncSession,
    cipher: DsnCipher,
    llm_router: LLMRouter,
    connector_id: str,
    request: ConnectorAuditRequest,
    *,
    actor: str,
) -> SchemaAuditResponse:
    """Introspect live connector database and run full schema hygiene audit."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    tables = await introspect_tables(dsn)
    findings, health_score = audit_schema(
        tables,
        default_retention_days=request.default_retention_days,
    )

    by_severity: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1

    llm_prompt = (
        f"Live schema audit on connector '{connector.name}' ({len(tables)} tables): "
        f"score {health_score}/100 with {len(findings)} findings ({by_severity})."
    )
    llm_result = await llm_router.generate(llm_prompt, task_hint="schema_audit")

    await append_audit_event(
        session,
        domain="schema_audit",
        action="schema_audit.live_analyze",
        actor=actor,
        resource_id=connector.id,
        details={
            "connector_name": connector.name,
            "tables_analyzed": len(tables),
            "health_score": health_score,
            "findings_count": len(findings),
        },
    )

    return SchemaAuditResponse(
        tables_analyzed=len(tables),
        health_score=health_score,
        findings_count=len(findings),
        findings_by_severity=by_severity,
        findings=findings,
        ai_summary=llm_result.text,
        llm_provider=llm_result.provider,
    )


async def scan_connector_table_pii(
    session: AsyncSession,
    cipher: DsnCipher,
    connector_id: str,
    table_name: str,
    request: ConnectorPiiScanRequest,
) -> PiiScanResponse:
    """Sample rows from a live table and scan them for PII."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    _, rows = await sample_table_rows(dsn, table_name, limit=request.limit)
    return await scan_pii(
        session,
        PiiScanRequest(
            records=rows,
            policy_name=request.policy_name,
            include_ner=request.include_ner,
        ),
    )


async def dedup_connector_table(
    session: AsyncSession,
    cipher: DsnCipher,
    llm_router: LLMRouter,
    connector_id: str,
    table_name: str,
    request: ConnectorDedupRequest,
) -> DedupAnalyzeResponse:
    """Sample rows from a live table and run duplicate entity clustering."""
    connector = await _load_connector(session, connector_id)
    dsn = cipher.decrypt(connector.dsn_encrypted)
    _, rows = await sample_table_rows(dsn, table_name, limit=request.limit)
    if len(rows) < 2:
        return DedupAnalyzeResponse(
            total_records=len(rows),
            cluster_count=0,
            duplicate_record_count=0,
            clusters=[],
            ai_summary="Fewer than 2 rows available for duplicate analysis.",
            llm_provider="mock",
        )
    return await analyze_duplicates(
        session,
        llm_router,
        DedupAnalyzeRequest(
            records=rows,
            id_field=request.id_field,
            threshold=request.threshold,
            survivorship=request.survivorship,
        ),
    )
