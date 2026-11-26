from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal, require_role, resolve_actor
from app.db.session import get_app_settings, get_db_session
from app.dedup.schemas import (
    DedupAnalyzeRequest,
    DedupAnalyzeResponse,
    ProposeMergeRequest,
)
from app.dedup.service import analyze_duplicates, propose_merge
from app.governance.schemas import GovernanceProposalResponse
from app.governance.service import serialize_proposal
from app.llm.router import LLMRouter

router = APIRouter(prefix="/dedup", tags=["dedup"])


def _get_llm_router(request: Request) -> LLMRouter:
    llm_router = getattr(request.app.state, "llm_router", None)
    if isinstance(llm_router, LLMRouter):
        return llm_router
    settings = get_app_settings(request)
    llm_router = LLMRouter(settings)
    request.app.state.llm_router = llm_router
    return llm_router


@router.post("/analyze", response_model=DedupAnalyzeResponse)
async def analyze_duplicates_endpoint(
    payload: DedupAnalyzeRequest,
    request: Request,
    _: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> DedupAnalyzeResponse:
    """Cluster fuzzy duplicate records and compute golden-record survivorship."""
    llm_router = _get_llm_router(request)
    return await analyze_duplicates(session, llm_router, payload)


@router.post("/propose-merge", response_model=GovernanceProposalResponse)
async def propose_merge_endpoint(
    payload: ProposeMergeRequest,
    principal: Principal = Depends(require_role("analyst")),
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Queue a human-in-the-loop merge proposal with full before-snapshot."""
    updated_payload = payload.model_copy(
        update={"created_by": resolve_actor(principal, payload.created_by)}
    )
    proposal = await propose_merge(session, updated_payload)
    return serialize_proposal(proposal)
