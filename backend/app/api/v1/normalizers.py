from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.governance.schemas import GovernanceProposalResponse
from app.governance.service import serialize_proposal
from app.normalizers.schemas import (
    NormalizerPreviewRequest,
    NormalizerPreviewResponse,
    NormalizerProposeRequest,
)
from app.normalizers.service import preview_normalization, propose_normalization

router = APIRouter(prefix="/normalizers", tags=["normalizers"])


@router.post("/preview", response_model=NormalizerPreviewResponse)
async def preview_normalizers_endpoint(
    payload: NormalizerPreviewRequest,
    session: AsyncSession = Depends(get_db_session),
) -> NormalizerPreviewResponse:
    """Preview canonical field normalization diffs without mutating stored data."""
    return await preview_normalization(session, payload)


@router.post("/propose", response_model=GovernanceProposalResponse)
async def propose_normalizers_endpoint(
    payload: NormalizerProposeRequest,
    session: AsyncSession = Depends(get_db_session),
) -> GovernanceProposalResponse:
    """Queue a human-reviewed bulk normalization proposal."""
    proposal = await propose_normalization(session, payload)
    return serialize_proposal(proposal)
