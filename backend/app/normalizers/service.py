from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GovernanceProposal
from app.governance.service import append_audit_event, create_proposal
from app.normalizers.engine import run_normalization_preview
from app.normalizers.schemas import (
    NormalizerPreviewRequest,
    NormalizerPreviewResponse,
    NormalizerProposeRequest,
)


async def preview_normalization(
    session: AsyncSession,
    request: NormalizerPreviewRequest,
) -> NormalizerPreviewResponse:
    """Compute a non-destructive normalization diff preview and append an audit log."""
    normalized_records, changes = run_normalization_preview(
        request.records,
        request.rules,
        id_field=request.id_field,
    )
    changed_cells = sum(1 for item in changes if item.normalized != item.original)
    invalid_cells = sum(1 for item in changes if not item.valid)

    await append_audit_event(
        session,
        domain="normalizers",
        action="normalizers.preview",
        actor="normalizer-engine",
        details={
            "total_records": len(request.records),
            "rules_count": len(request.rules),
            "changed_cells": changed_cells,
            "invalid_cells": invalid_cells,
        },
    )

    return NormalizerPreviewResponse(
        total_records=len(request.records),
        changed_cells=changed_cells,
        invalid_cells=invalid_cells,
        changes=changes,
        normalized_records=normalized_records,
    )


async def propose_normalization(
    session: AsyncSession,
    request: NormalizerProposeRequest,
) -> GovernanceProposal:
    """Stage normalization transforms as an HITL proposal with before-snapshot."""
    normalized_records, changes = run_normalization_preview(
        request.records,
        request.rules,
        id_field=request.id_field,
    )
    changed_cells = sum(1 for item in changes if item.normalized != item.original)
    invalid_cells = sum(1 for item in changes if not item.valid)

    summary = (
        f"Normalize {changed_cells} cells across {len(request.records)} records using "
        f"{len(request.rules)} rules ({invalid_cells} validation warnings)."
    )

    payload_data: dict[str, object] = {
        "rules": [rule.model_dump() for rule in request.rules],
        "id_field": request.id_field,
        "changes_count": changed_cells,
        "invalid_cells": invalid_cells,
        "normalized_records": normalized_records,
    }
    if request.connector_id:
        payload_data["connector_id"] = request.connector_id
    if request.target_table:
        payload_data["target_table"] = request.target_table

    return await create_proposal(
        session,
        domain="normalizers",
        action_type="bulk_normalize",
        title=request.title,
        summary=summary,
        risk_level="medium",
        payload=payload_data,
        before_snapshot=request.records,
        created_by=request.created_by,
    )
