import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import build_test_app


def test_production_validation_requires_auth_enabled() -> None:
    cfg = Settings(
        app_env="production",
        auth_secret_key="x" * 40,
        cors_origins="https://governance.example.com",
        auth_required=False,
    )
    with pytest.raises(RuntimeError, match="AUTH_REQUIRED"):
        create_app(cfg)


@pytest.mark.asyncio
async def test_jwt_api_key_rbac_and_four_eyes_enforcement() -> None:
    app = build_test_app(
        auth_required=True,
        auth_api_keys="viewer-key:viewer:ci-viewer,admin-key:admin:ci-admin",
        enforce_four_eyes=True,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Unauthenticated request rejected with 401
        unauth = await client.get("/api/v1/governance/proposals")
        assert unauth.status_code == 401

        # API key works for viewer role, blocked for analyst scan
        viewer_headers = {"X-API-Key": "viewer-key"}
        me_viewer = await client.get("/api/v1/auth/me", headers=viewer_headers)
        assert me_viewer.status_code == 200
        assert me_viewer.json()["role"] == "viewer"

        denied_scan = await client.post(
            "/api/v1/pii/scan",
            json={"text": "test@example.com"},
            headers=viewer_headers,
        )
        assert denied_scan.status_code == 403

        # Mint JWTs for analyst and steward
        analyst_tok = (
            await client.post(
                "/api/v1/auth/token",
                json={"username": "alice-analyst", "role": "analyst"},
            )
        ).json()["access_token"]
        steward_tok = (
            await client.post(
                "/api/v1/auth/token",
                json={"username": "bob-steward", "role": "steward"},
            )
        ).json()["access_token"]
        analyst_headers = {"Authorization": f"Bearer {analyst_tok}"}
        steward_headers = {"Authorization": f"Bearer {steward_tok}"}

        # Analyst can propose merge, cannot approve
        prop = (
            await client.post(
                "/api/v1/dedup/propose-merge",
                json={
                    "cluster_id": "cluster-1",
                    "source_records": [{"id": "1", "name": "A"}, {"id": "2", "name": "A"}],
                    "golden_record": {"id": "1", "name": "A"},
                },
                headers=analyst_headers,
            )
        ).json()
        assert prop["created_by"] == "alice-analyst"

        analyst_approve = await client.post(
            f"/api/v1/governance/proposals/{prop['id']}/approve",
            json={"reviewer": "spoofed", "notes": "self"},
            headers=analyst_headers,
        )
        assert analyst_approve.status_code == 403

        # Four-eyes: even a steward who created a proposal cannot approve their own proposal
        steward_prop = (
            await client.post(
                "/api/v1/dedup/propose-merge",
                json={
                    "cluster_id": "cluster-2",
                    "source_records": [{"id": "3", "name": "B"}, {"id": "4", "name": "B"}],
                    "golden_record": {"id": "3", "name": "B"},
                },
                headers=steward_headers,
            )
        ).json()
        self_approve = await client.post(
            f"/api/v1/governance/proposals/{steward_prop['id']}/approve",
            json={"reviewer": "someone-else", "notes": "attempt"},
            headers=steward_headers,
        )
        assert self_approve.status_code == 409
        assert "Separation of duties" in self_approve.json()["detail"]

        # Steward CAN approve analyst's proposal
        ok_approve = await client.post(
            f"/api/v1/governance/proposals/{prop['id']}/approve",
            json={"reviewer": "ignored-when-jwt", "notes": "Looks good"},
            headers=steward_headers,
        )
        assert ok_approve.status_code == 200
        assert ok_approve.json()["reviewed_by"] == "bob-steward"

        # Non-admin cannot register connector
        denied_conn = await client.post(
            "/api/v1/connectors",
            json={"name": "test", "connector_type": "sqlite", "dsn": "sqlite:///x.db"},
            headers=steward_headers,
        )
        assert denied_conn.status_code == 403


@pytest.mark.asyncio
async def test_rate_limiter_returns_429_and_bypasses_health() -> None:
    app = build_test_app(rate_limit_enabled=True, rate_limit_requests_per_minute=2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/api/v1/governance/proposals")
        r2 = await client.get("/api/v1/governance/proposals")
        r3 = await client.get("/api/v1/governance/proposals")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r3.status_code == 429
        assert "retry-after" in r3.headers

        # Health probe remains exempt
        health = await client.get("/api/v1/health/live")
        assert health.status_code == 200
