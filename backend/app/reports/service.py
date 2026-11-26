import csv
import io
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundJob, DataConnector, GovernanceProposal
from app.governance.schemas import AuditEventResponse
from app.governance.service import (
    list_audit_events,
    serialize_audit_event,
    verify_audit_chain,
)
from app.pii.vault import PiiVault
from app.reports.schemas import ComplianceReportResponse


async def build_compliance_report(
    session: AsyncSession,
    vault: PiiVault,
) -> ComplianceReportResponse:
    """Aggregate posture metrics, HITL proposal counts, and verified audit proof."""
    vault_by_type = await vault.stats(session)

    prop_rows = (
        await session.execute(select(GovernanceProposal.domain, GovernanceProposal.status))
    ).all()
    by_status: dict[str, int] = {}
    by_domain: dict[str, int] = {}
    for domain, prop_status in prop_rows:
        by_status[prop_status] = by_status.get(prop_status, 0) + 1
        by_domain[domain] = by_domain.get(domain, 0) + 1

    connectors_total = int(
        (await session.execute(select(func.count(DataConnector.id)))).scalar_one() or 0
    )

    job_rows = (await session.execute(select(BackgroundJob.status))).all()
    jobs_by_status: dict[str, int] = {}
    for (job_status,) in job_rows:
        jobs_by_status[job_status] = jobs_by_status.get(job_status, 0) + 1

    audit_chain = await verify_audit_chain(session)
    recent_events = [
        serialize_audit_event(ev) for ev in await list_audit_events(session, limit=50)
    ]

    return ComplianceReportResponse(
        generated_at=datetime.now(UTC),
        vault_total_tokens=sum(vault_by_type.values()),
        vault_by_entity_type=vault_by_type,
        proposals_total=len(prop_rows),
        proposals_by_status=by_status,
        proposals_by_domain=by_domain,
        connectors_total=connectors_total,
        jobs_total=len(job_rows),
        jobs_by_status=jobs_by_status,
        audit_chain=audit_chain,
        recent_audit_events=recent_events,
    )


def render_markdown_report(report: ComplianceReportResponse) -> str:
    """Render compliance report as portable Markdown suitable for audits."""
    chain_status = "VALID" if report.audit_chain.valid else "INVALID"
    lines = [
        "# AI Data Governance Compliance Report",
        "",
        f"- **Generated At:** {report.generated_at.isoformat()}",
        f"- **Audit Chain Integrity:** {chain_status} "
        f"({report.audit_chain.checked_count} events checked)",
        f"- **Latest Chain Hash:** `{report.audit_chain.latest_hash or 'none'}`",
        f"- **Encrypted PII Vault Tokens:** {report.vault_total_tokens}",
        f"- **Registered Database Connectors:** {report.connectors_total}",
        f"- **Governance Proposals:** {report.proposals_total}",
        f"- **Background Jobs:** {report.jobs_total}",
        "",
        "## Proposals by Status",
        "",
    ]
    if report.proposals_by_status:
        for k, v in sorted(report.proposals_by_status.items()):
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- None")

    lines.extend(["", "## Vault Tokens by Entity Type", ""])
    if report.vault_by_entity_type:
        for k, v in sorted(report.vault_by_entity_type.items()):
            lines.append(f"- `{k}`: {v}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Recent Immutable Audit Events",
            "",
            "| Seq | Domain | Action | Actor | Hash Prefix |",
            "|---:|---|---|---|---|",
        ]
    )
    for ev in report.recent_audit_events[:25]:
        lines.append(
            f"| {ev.sequence_no} | {ev.domain} | `{ev.action}` | {ev.actor} | "
            f"`{ev.event_hash[:12]}` |"
        )
    return "\n".join(lines) + "\n"


def render_csv_audit_export(events: list[AuditEventResponse]) -> str:
    """Render audit trail entries as RFC-4180 CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "sequence_no",
            "created_at",
            "domain",
            "action",
            "actor",
            "resource_id",
            "prev_hash",
            "event_hash",
            "details_json",
        ]
    )
    for ev in events:
        writer.writerow(
            [
                ev.sequence_no,
                ev.created_at.isoformat(),
                ev.domain,
                ev.action,
                ev.actor,
                ev.resource_id or "",
                ev.prev_hash,
                ev.event_hash,
                json.dumps(ev.details, sort_keys=True),
            ]
        )
    return buf.getvalue()
