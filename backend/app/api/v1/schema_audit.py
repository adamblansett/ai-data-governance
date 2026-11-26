from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal, require_role, resolve_actor
from app.db.session import get_app_settings, get_db_session
from app.governance.schemas import GovernanceProposalResponse
from app.governance.service import serialize_proposal
from app.llm.router import LLMRouter
from app.schema_audit.schemas import (
    ProposeRemediationRequest,
    SchemaAuditRequest,
    SchemaAuditResponse,
)
from app.schema_audit.service import propose_remediation, run_schema_audit

router = APIRouter(prefix="/schema-audit", tags=["schema_audit"])


def _get_llm_router(request: Request) -> LLMRouter:
    llm_router = getattr(request.app.state, "llm_router", None)
    if isinstance(llm_router, LLMRouter):
        return llm_router
    settings = get_app_settings(request)
    llm_router = LLMRouter(settings)
    request.app.state.llm_router = llm_router
    return llm_router


@router.post("/analyze", response_model=SchemaAuditResponse)
async def analyze_schema_endpoint(
    payload: SchemaAuditRequest,
    request: Request,
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> SchemaAuditResponse:
    """Analyze PostgreSQL DDL and metadata catalog for hygiene issues."""
    llm_router = _get_llm_router(request)
    return await run_schema_audit(session, llm_router, payload)


@router.post("/propose-remediation", response_model=GovernanceProposalResponse)
async def propose_remediation_endpoint(
    payload: ProposeRemediationRequest,
    principal: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Queue SQL remediation findings for human-in-the-loop review and approval."""
    updated_payload = payload.model_copy(
        update={"created_by": resolve_actor(principal, payload.created_by)}
    )
    try:
        proposal = await propose_remediation(session, updated_payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return serialize_proposal(proposal)
