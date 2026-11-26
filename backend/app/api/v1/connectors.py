from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.crypto import DsnCipher
from app.connectors.ingest import parse_uploaded_file
from app.connectors.schemas import (
    ConnectorAuditRequest,
    ConnectorCreateRequest,
    ConnectorDedupRequest,
    ConnectorPiiScanRequest,
    ConnectorResponse,
    ConnectorSampleResponse,
    ConnectorTestResponse,
    FileIngestResponse,
)
from app.connectors.service import (
    ConnectorConflictError,
    ConnectorNotFoundError,
    audit_connector_schema,
    create_connector,
    dedup_connector_table,
    delete_connector,
    introspect_connector_tables,
    list_connectors,
    sample_connector_table,
    scan_connector_table_pii,
    serialize_connector,
    test_connector,
)
from app.core.security import Principal, require_role
from app.db.session import get_app_settings, get_db_session
from app.dedup.schemas import DedupAnalyzeResponse
from app.llm.router import LLMRouter
from app.pii.schemas import PiiScanResponse
from app.schema_audit.schemas import SchemaAuditResponse

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _get_cipher(request: Request) -> DsnCipher:
    cipher = getattr(request.app.state, "dsn_cipher", None)
    if isinstance(cipher, DsnCipher):
        return cipher
    cipher = DsnCipher(get_app_settings(request))
    request.app.state.dsn_cipher = cipher
    return cipher


def _get_llm_router(request: Request) -> LLMRouter:
    llm_router = getattr(request.app.state, "llm_router", None)
    if isinstance(llm_router, LLMRouter):
        return llm_router
    llm_router = LLMRouter(get_app_settings(request))
    request.app.state.llm_router = llm_router
    return llm_router


@router.post("", response_model=ConnectorResponse, status_code=status.HTTP_201_CREATED)
async def register_connector(
    payload: ConnectorCreateRequest,
    request: Request,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorResponse:
    """Register an encrypted database connector (admin only)."""
    cipher = _get_cipher(request)
    try:
        connector = await create_connector(
            session,
            cipher,
            payload,
            created_by=principal.sub,
        )
    except ConnectorConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return serialize_connector(connector, cipher)


@router.get("", response_model=list[ConnectorResponse])
async def get_connectors(
    request: Request,
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConnectorResponse]:
    """List registered database connectors with masked DSNs."""
    cipher = _get_cipher(request)
    connectors = await list_connectors(session)
    return [serialize_connector(item, cipher) for item in connectors]


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_connector(
    connector_id: str,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a registered database connector (admin only)."""
    try:
        await delete_connector(session, connector_id, actor=principal.sub)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{connector_id}/test", response_model=ConnectorTestResponse)
async def test_connector_endpoint(
    connector_id: str,
    request: Request,
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorTestResponse:
    """Test live connectivity to a registered database connector."""
    cipher = _get_cipher(request)
    try:
        return await test_connector(session, cipher, connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{connector_id}/tables", response_model=list[dict[str, Any]])
async def introspect_tables_endpoint(
    connector_id: str,
    request: Request,
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Introspect live table, key, index, and orphan-FK metadata."""
    cipher = _get_cipher(request)
    try:
        return await introspect_connector_tables(session, cipher, connector_id)
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{connector_id}/tables/{table_name}/sample", response_model=ConnectorSampleResponse)
async def sample_table_endpoint(
    connector_id: str,
    table_name: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> ConnectorSampleResponse:
    """Sample bounded rows from a live database table."""
    cipher = _get_cipher(request)
    try:
        return await sample_connector_table(
            session,
            cipher,
            connector_id,
            table_name,
            limit=limit,
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/{connector_id}/audit", response_model=SchemaAuditResponse)
async def audit_connector_endpoint(
    connector_id: str,
    request: Request,
    payload: ConnectorAuditRequest | None = None,
    principal: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> SchemaAuditResponse:
    """Run live schema hygiene audit against an introspected database connector."""
    cipher = _get_cipher(request)
    llm_router = _get_llm_router(request)
    try:
        return await audit_connector_schema(
            session,
            cipher,
            llm_router,
            connector_id,
            payload or ConnectorAuditRequest(),
            actor=principal.sub,
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{connector_id}/tables/{table_name}/pii-scan", response_model=PiiScanResponse)
async def scan_table_pii_endpoint(
    connector_id: str,
    table_name: str,
    request: Request,
    payload: ConnectorPiiScanRequest | None = None,
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> PiiScanResponse:
    """Sample a live database table and scan its rows for PII."""
    cipher = _get_cipher(request)
    try:
        return await scan_connector_table_pii(
            session,
            cipher,
            connector_id,
            table_name,
            payload or ConnectorPiiScanRequest(),
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post(
    "/{connector_id}/tables/{table_name}/dedup-analyze",
    response_model=DedupAnalyzeResponse,
)
async def dedup_table_endpoint(
    connector_id: str,
    table_name: str,
    request: Request,
    payload: ConnectorDedupRequest | None = None,
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> DedupAnalyzeResponse:
    """Sample a live database table and analyze duplicate clusters."""
    cipher = _get_cipher(request)
    llm_router = _get_llm_router(request)
    try:
        return await dedup_connector_table(
            session,
            cipher,
            llm_router,
            connector_id,
            table_name,
            payload or ConnectorDedupRequest(),
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/ingest/file", response_model=FileIngestResponse)
async def ingest_file_endpoint(
    file: UploadFile = File(...),
    max_rows: int = Query(default=500, ge=1, le=2000),
    _: Principal = Depends(require_role("analyst")),
) -> FileIngestResponse:
    """Parse an uploaded CSV or JSON file into normalized record dicts."""
    content = await file.read()
    try:
        return parse_uploaded_file(file.filename or "upload.csv", content, max_rows=max_rows)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
