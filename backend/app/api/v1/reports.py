from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import Principal, require_role
from app.db.session import get_app_settings, get_db_session
from app.pii.vault import PiiVault
from app.reports.schemas import ComplianceReportResponse
from app.reports.service import (
    build_compliance_report,
    render_csv_audit_export,
    render_markdown_report,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _get_vault(request: Request) -> PiiVault:
    vault = getattr(request.app.state, "pii_vault", None)
    if isinstance(vault, PiiVault):
        return vault
    vault = PiiVault(get_app_settings(request))
    request.app.state.pii_vault = vault
    return vault


@router.get("/compliance", response_model=ComplianceReportResponse)
async def export_compliance_report(
    request: Request,
    export_format: Literal["json", "markdown", "csv"] = Query(default="json", alias="format"),
    _: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> ComplianceReportResponse | Response:
    """Export governance compliance summary and audit proof in JSON, Markdown, or CSV."""
    vault = _get_vault(request)
    report = await build_compliance_report(session, vault)

    if export_format == "markdown":
        md_body = render_markdown_report(report)
        return Response(
            content=md_body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="governance-compliance.md"'},
        )
    if export_format == "csv":
        csv_body = render_csv_audit_export(report.recent_audit_events)
        return Response(
            content=csv_body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="governance-audit.csv"'},
        )
    return report
