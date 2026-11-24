import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.db.models import AuditEvent
from app.db.session import DatabaseManager
from app.governance.service import verify_audit_chain
from tests.conftest import build_test_app


@pytest.mark.asyncio
async def test_hitl_approval_apply_rollback_and_rejection_lifecycle() -> None:
    app = build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Create proposal via dedup endpoint
        create_res = await client.post(
            "/api/v1/dedup/propose-merge",
            json={
                "cluster_id": "cluster-1",
                "source_records": [
                    {"id": "1", "name": "Jane Doe"},
                    {"id": "2", "name": "Doe, Jane", "email": "jane@acme.com"},
                ],
                "golden_record": {"id": "2", "name": "Jane Doe", "email": "jane@acme.com"},
            },
        )
        assert create_res.status_code == 200
        proposal_id = create_res.json()["id"]
        assert create_res.json()["status"] == "pending_review"

        # Applying without approval MUST fail with HTTP 409
        premature_apply = await client.post(
            f"/api/v1/governance/proposals/{proposal_id}/apply",
            json={"actor": "auto-runner"},
        )
        assert premature_apply.status_code == 409

        # Approve -> Apply -> Rollback
        approve_res = await client.post(
            f"/api/v1/governance/proposals/{proposal_id}/approve",
            json={"reviewer": "alice-steward", "notes": "Verified golden record"},
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["status"] == "approved"
        assert approve_res.json()["reviewed_by"] == "alice-steward"

        apply_res = await client.post(
            f"/api/v1/governance/proposals/{proposal_id}/apply",
            json={"actor": "alice-steward"},
        )
        assert apply_res.status_code == 200
        applied = apply_res.json()
        assert applied["status"] == "applied"
        assert applied["after_snapshot"]["golden_record"]["email"] == "jane@acme.com"

        rollback_res = await client.post(
            f"/api/v1/governance/proposals/{proposal_id}/rollback",
            json={"actor": "alice-steward", "reason": "Reverting test merge"},
        )
        assert rollback_res.status_code == 200
        rolled = rollback_res.json()
        assert rolled["status"] == "rolled_back"
        assert len(rolled["before_snapshot"]) == 2

        # Separate rejection flow cannot subsequently be applied
        create_res_2 = await client.post(
            "/api/v1/normalizers/propose",
            json={
                "records": [{"id": "1", "email": "BOB@ACME.COM"}],
                "rules": [{"field": "email", "kind": "email"}],
            },
        )
        prop2_id = create_res_2.json()["id"]

        reject_res = await client.post(
            f"/api/v1/governance/proposals/{prop2_id}/reject",
            json={"reviewer": "alice-steward", "notes": "Hold for schema freeze"},
        )
        assert reject_res.status_code == 200
        assert reject_res.json()["status"] == "rejected"

        apply_rejected = await client.post(
            f"/api/v1/governance/proposals/{prop2_id}/apply",
            json={"actor": "alice-steward"},
        )
        assert apply_rejected.status_code == 409


@pytest.mark.asyncio
async def test_audit_hash_chain_detects_tampering() -> None:
    app = build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/v1/pii/scan", json={"text": "Email alice@acme.com"})
        await client.post(
            "/api/v1/normalizers/preview",
            json={
                "records": [{"id": "1", "email": "BOB@ACME.COM"}],
                "rules": [{"field": "email", "kind": "email"}],
            },
        )

        verify_ok = await client.get("/api/v1/governance/audit/verify")
        assert verify_ok.status_code == 200
        assert verify_ok.json()["valid"] is True
        assert verify_ok.json()["checked_count"] == 2

        # Tamper directly with sequence 1 in the database
        db: DatabaseManager = app.state.db
        async with db.session_factory() as session:
            await session.execute(
                update(AuditEvent)
                .where(AuditEvent.sequence_no == 1)
                .values(actor="tampered-actor")
            )
            await session.commit()

            broken = await verify_audit_chain(session)
            assert broken.valid is False
            assert broken.broken_at_sequence == 1
