import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import build_test_app


def _create_live_crm_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                tier TEXT
            );
            INSERT INTO customers VALUES
                (1, 'Jane Doe', '  JANE.DOE@Acme.COM ', '(555) 234-5678', NULL),
                (2, 'Doe, Jane', 'jane.doe@acme.com', '+1-555-234-5678', 'Enterprise'),
                (3, 'Devon Brooks', 'DEVON@Globex.IO', '415-555-0199', 'Pro');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _read_customers(db_path: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, name, email, phone, tier FROM customers ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_full_stack_e2e_connector_hitl_apply_rollback_and_audit(tmp_path: Path) -> None:
    crm_db = tmp_path / "crm_live.db"
    _create_live_crm_db(crm_db)
    original_rows = _read_customers(crm_db)

    app = build_test_app(auth_required=True, enforce_four_eyes=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_tok = (
            await client.post("/api/v1/auth/token", json={"username": "admin-1", "role": "admin"})
        ).json()["access_token"]
        analyst_tok = (
            await client.post(
                "/api/v1/auth/token", json={"username": "analyst-1", "role": "analyst"}
            )
        ).json()["access_token"]
        steward_tok = (
            await client.post(
                "/api/v1/auth/token", json={"username": "steward-1", "role": "steward"}
            )
        ).json()["access_token"]

        admin_h = {"Authorization": f"Bearer {admin_tok}"}
        analyst_h = {"Authorization": f"Bearer {analyst_tok}"}
        steward_h = {"Authorization": f"Bearer {steward_tok}"}

        # 1. Admin registers writable SQLite connector
        conn_res = await client.post(
            "/api/v1/connectors",
            json={
                "name": "crm-live",
                "connector_type": "sqlite",
                "dsn": f"sqlite:///{crm_db.as_posix()}",
                "read_only": False,
            },
            headers=admin_h,
        )
        assert conn_res.status_code == 201
        conn_id = conn_res.json()["id"]

        # 2. Analyst samples live rows and stages bulk normalization tied to connector
        sample = (
            await client.get(
                f"/api/v1/connectors/{conn_id}/tables/customers/sample", headers=analyst_h
            )
        ).json()["rows"]
        norm_prop = (
            await client.post(
                "/api/v1/normalizers/propose",
                json={
                    "records": sample,
                    "rules": [
                        {"field": "email", "kind": "email"},
                        {"field": "phone", "kind": "phone"},
                    ],
                    "connector_id": conn_id,
                    "target_table": "customers",
                },
                headers=analyst_h,
            )
        ).json()

        # 3. Steward approves and applies normalization transactionally to crm_live.db
        await client.post(
            f"/api/v1/governance/proposals/{norm_prop['id']}/approve",
            json={"reviewer": "ignored", "notes": "Approved for CRM cleanup"},
            headers=steward_h,
        )
        apply_norm = await client.post(
            f"/api/v1/governance/proposals/{norm_prop['id']}/apply",
            json={"actor": "ignored"},
            headers=steward_h,
        )
        assert apply_norm.status_code == 200
        assert apply_norm.json()["after_snapshot"]["executed_on_connector"] is True

        normalized_rows = _read_customers(crm_db)
        assert normalized_rows[0][2] == "jane.doe@acme.com"
        assert normalized_rows[0][3] == "+15552345678"
        assert normalized_rows[2][2] == "devon@globex.io"

        # 4. Rollback restores exact original DB rows
        rb_norm = await client.post(
            f"/api/v1/governance/proposals/{norm_prop['id']}/rollback",
            json={"actor": "ignored", "reason": "Verify transactional rollback"},
            headers=steward_h,
        )
        assert rb_norm.status_code == 200
        assert _read_customers(crm_db) == original_rows

        # 5. Analyst runs live dedup and stages transactional merge
        dedup_res = (
            await client.post(
                f"/api/v1/connectors/{conn_id}/tables/customers/dedup-analyze",
                json={"threshold": 0.78, "survivorship": "most_complete"},
                headers=analyst_h,
            )
        ).json()
        assert dedup_res["cluster_count"] == 1
        cluster = dedup_res["clusters"][0]

        merge_prop = (
            await client.post(
                "/api/v1/dedup/propose-merge",
                json={
                    "cluster_id": cluster["cluster_id"],
                    "source_records": cluster["records"],
                    "golden_record": cluster["golden_record"],
                    "connector_id": conn_id,
                    "target_table": "customers",
                },
                headers=analyst_h,
            )
        ).json()

        await client.post(
            f"/api/v1/governance/proposals/{merge_prop['id']}/approve",
            json={"reviewer": "ignored", "notes": "Merge verified"},
            headers=steward_h,
        )
        await client.post(
            f"/api/v1/governance/proposals/{merge_prop['id']}/apply",
            json={"actor": "ignored"},
            headers=steward_h,
        )
        merged_rows = _read_customers(crm_db)
        assert len(merged_rows) == 2

        # Rollback merge re-inserts deleted duplicate row cleanly
        await client.post(
            f"/api/v1/governance/proposals/{merge_prop['id']}/rollback",
            json={"actor": "ignored", "reason": "Undo merge"},
            headers=steward_h,
        )
        assert _read_customers(crm_db) == original_rows

        # 6. Compliance report + audit chain verification
        report = (
            await client.get("/api/v1/reports/compliance?format=json", headers=steward_h)
        ).json()
        assert report["audit_chain"]["valid"] is True
        assert report["connectors_total"] == 1
        assert report["proposals_by_status"]["rolled_back"] == 2
