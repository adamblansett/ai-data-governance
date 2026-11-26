import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import build_test_app


@pytest.mark.asyncio
async def test_inline_and_background_jobs_and_compliance_reports() -> None:
    app = build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Inline job
        inline_res = await client.post(
            "/api/v1/jobs/submit",
            json={
                "job_type": "pii_scan",
                "execution_mode": "inline",
                "params": {"text": "Email alice@acme.com and SSN 123-45-6789"},
            },
        )
        assert inline_res.status_code == 200
        inline_job = inline_res.json()
        assert inline_job["status"] == "completed"
        assert inline_job["result"]["total_findings"] == 2

        # 2. Background job
        bg_res = await client.post(
            "/api/v1/jobs/submit",
            json={
                "job_type": "schema_audit",
                "execution_mode": "background",
                "params": {"ddl_sql": "CREATE TABLE scratch (payload TEXT);"},
            },
        )
        assert bg_res.status_code == 200
        bg_id = bg_res.json()["id"]

        final_bg = bg_res.json()
        for _ in range(40):
            poll = await client.get(f"/api/v1/jobs/{bg_id}")
            assert poll.status_code == 200
            final_bg = poll.json()
            if final_bg["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.05)

        assert final_bg["status"] == "completed"
        assert final_bg["result"]["findings_count"] >= 1

        # 3. Compliance report exports (json, markdown, csv)
        json_rep = await client.get("/api/v1/reports/compliance?format=json")
        assert json_rep.status_code == 200
        rep_data = json_rep.json()
        assert rep_data["jobs_total"] == 2
        assert rep_data["audit_chain"]["valid"] is True

        md_rep = await client.get("/api/v1/reports/compliance?format=markdown")
        assert md_rep.status_code == 200
        assert "# AI Data Governance Compliance Report" in md_rep.text
        assert "123-45-6789" not in md_rep.text

        csv_rep = await client.get("/api/v1/reports/compliance?format=csv")
        assert csv_rep.status_code == 200
        assert "sequence_no,created_at,domain,action" in csv_rep.text
