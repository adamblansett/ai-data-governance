from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_app_settings, get_db_session
from app.pii.schemas import (
    PiiDetokenizeRequest,
    PiiDetokenizeResponse,
    PiiMaskRequest,
    PiiMaskResponse,
    PiiScanRequest,
    PiiScanResponse,
    PiiVaultStatsResponse,
)
from app.pii.service import detokenize_pii, get_vault_stats, mask_pii, scan_pii
from app.pii.vault import PiiVault

router = APIRouter(prefix="/pii", tags=["pii"])


def _get_vault(request: Request) -> PiiVault:
    vault = getattr(request.app.state, "pii_vault", None)
    if isinstance(vault, PiiVault):
        return vault
    settings = get_app_settings(request)
    vault = PiiVault(settings)
    request.app.state.pii_vault = vault
    return vault


@router.post("/scan", response_model=PiiScanResponse)
async def scan_pii_endpoint(
    payload: PiiScanRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PiiScanResponse:
    """Scan text or structured JSON records for PII entities."""
    return await scan_pii(session, payload)


@router.post("/mask", response_model=PiiMaskResponse)
async def mask_pii_endpoint(
    payload: PiiMaskRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> PiiMaskResponse:
    """Apply redact, mask, hash, or reversible vault tokenization to PII."""
    vault = _get_vault(request)
    return await mask_pii(session, vault, payload)


@router.post("/detokenize", response_model=PiiDetokenizeResponse)
async def detokenize_pii_endpoint(
    payload: PiiDetokenizeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> PiiDetokenizeResponse:
    """Resolve stored PII vault tokens with mandatory actor and reason audit logging."""
    vault = _get_vault(request)
    return await detokenize_pii(
        session,
        vault,
        tokens=payload.tokens,
        actor=payload.actor,
        reason=payload.reason,
    )


@router.get("/vault/stats", response_model=PiiVaultStatsResponse)
async def vault_stats_endpoint(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> PiiVaultStatsResponse:
    """Return aggregated counts of encrypted tokens stored in the PII vault."""
    vault = _get_vault(request)
    return await get_vault_stats(session, vault)
