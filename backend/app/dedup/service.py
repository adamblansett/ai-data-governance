from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GovernanceProposal
from app.dedup.engine import analyze_clusters
from app.dedup.schemas import (
    DedupAnalyzeRequest,
    DedupAnalyzeResponse,
    ProposeMergeRequest,
)
from app.governance.service import append_audit_event, create_proposal
from app.llm.router import LLMRouter


async def analyze_duplicates(
    session: AsyncSession,
    llm_router: LLMRouter,
    request: DedupAnalyzeRequest,
) -> DedupAnalyzeResponse:
    """Run blocking & similarity resolution and enrich with AI guidance."""
    clusters = analyze_clusters(
        request.records,
        id_field=request.id_field,
        updated_at_field=request.updated_at_field,
        threshold=request.threshold,
        weights=request.weights,
        survivorship=request.survivorship,
        field_survivorship=request.field_survivorship,
    )
    duplicate_count = sum(len(cluster.record_ids) for cluster in clusters)

    llm_prompt = (
        f"Analyzed {len(request.records)} records with threshold {request.threshold} "
        f"and survivorship '{request.survivorship}'; found {len(clusters)} duplicate clusters "
        f"covering {duplicate_count} records."
    )
    llm_result = await llm_router.generate(llm_prompt, task_hint="dedup")

    await append_audit_event(
        session,
        domain="dedup",
        action="dedup.analyze",
        actor="dedup-engine",
        details={
            "total_records": len(request.records),
            "cluster_count": len(clusters),
            "duplicate_record_count": duplicate_count,
            "threshold": request.threshold,
            "survivorship": request.survivorship,
        },
    )

    return DedupAnalyzeResponse(
        total_records=len(request.records),
        cluster_count=len(clusters),
        duplicate_record_count=duplicate_count,
        clusters=clusters,
        ai_summary=llm_result.text,
        llm_provider=llm_result.provider,
    )


async def propose_merge(
    session: AsyncSession,
    request: ProposeMergeRequest,
) -> GovernanceProposal:
    """Create a pending_review HITL proposal for merging a duplicate cluster."""
    record_ids = [
        str(rec.get(request.id_field, f"row-{idx + 1}"))
        for idx, rec in enumerate(request.source_records)
    ]
    title = f"Merge {len(record_ids)} duplicate records ({request.cluster_id})"
    summary = (
        f"{request.rationale}. Source IDs: {', '.join(record_ids)} -> "
        f"golden ID: {request.golden_record.get(request.id_field, record_ids[0])}."
    )
    payload_data: dict[str, object] = {
        "cluster_id": request.cluster_id,
        "record_ids": record_ids,
        "id_field": request.id_field,
        "golden_record": request.golden_record,
        "rationale": request.rationale,
    }
    if request.connector_id:
        payload_data["connector_id"] = request.connector_id
    if request.target_table:
        payload_data["target_table"] = request.target_table

    return await create_proposal(
        session,
        domain="dedup",
        action_type="record_merge",
        title=title,
        summary=summary,
        risk_level="high",
        payload=payload_data,
        before_snapshot=request.source_records,
        created_by=request.created_by,
    )
