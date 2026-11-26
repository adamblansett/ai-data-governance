import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import build_test_app


def _seed_target_sqlite(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL,
                ssn TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                account_id INTEGER REFERENCES accounts(id),
                total REAL NOT NULL
            );
            CREATE TABLE scratch_events (
                payload TEXT
            );
            INSERT INTO accounts VALUES (1, '  ALICE@Acme.COM ', '123-45-6789', '2024-01-01');
            INSERT INTO orders VALUES (10, 1, 50.0);
            INSERT INTO orders VALUES (11, 999, 75.0);
            """
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_live_sqlite_connector_introspection_sample_audit_and_readonly_block(
    tmp_path: Path,
) -> None:
    target_db = tmp_path / "target_warehouse.db"
    _seed_target_sqlite(target_db)
    app = build_test_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_res = await client.post(
            "/api/v1/connectors",
            json={
                "name": "warehouse-ro",
                "connector_type": "sqlite",
                "dsn": f"sqlite:///{target_db.as_posix()}",
                "read_only": True,
                "description": "Target warehouse",
            },
        )
        assert create_res.status_code == 201
        conn_data = create_res.json()
        conn_id = conn_data["id"]
        assert conn_data["name"] == "warehouse-ro"

        test_res = await client.post(f"/api/v1/connectors/{conn_id}/test")
        assert test_res.status_code == 200
        assert test_res.json()["ok"] is True
        assert test_res.json()["table_count"] == 3

        tables_res = await client.get(f"/api/v1/connectors/{conn_id}/tables")
        assert tables_res.status_code == 200
        tables = tables_res.json()
        orders_meta = next(t for t in tables if t["name"] == "orders")
        assert orders_meta["foreign_keys"][0]["orphan_count"] == 1

        audit_res = await client.post(f"/api/v1/connectors/{conn_id}/audit")
        assert audit_res.status_code == 200
        categories = {f["category"] for f in audit_res.json()["findings"]}
        assert {"orphaned_fk", "missing_pk", "pii_column_risk"}.issubset(categories)

        sample_res = await client.get(f"/api/v1/connectors/{conn_id}/tables/accounts/sample")
        assert sample_res.status_code == 200
        assert sample_res.json()["row_count_sampled"] == 1

        pii_res = await client.post(f"/api/v1/connectors/{conn_id}/tables/accounts/pii-scan")
        assert pii_res.status_code == 200
        assert pii_res.json()["entity_counts"]["SSN"] == 1
        assert pii_res.json()["entity_counts"]["EMAIL"] == 1

        # Read-only connector blocks live apply execution
        prop = (
            await client.post(
                "/api/v1/normalizers/propose",
                json={
                    "records": [{"id": 1, "email": "  ALICE@Acme.COM "}],
                    "rules": [{"field": "email", "kind": "email"}],
                    "connector_id": conn_id,
                    "target_table": "accounts",
                },
            )
        ).json()
        await client.post(
            f"/api/v1/governance/proposals/{prop['id']}/approve",
            json={"reviewer": "steward-1"},
        )
        apply_res = await client.post(
            f"/api/v1/governance/proposals/{prop['id']}/apply",
            json={"actor": "steward-1"},
        )
        assert apply_res.status_code == 409
        assert "read-only" in apply_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_csv_and_json_file_upload_ingestion() -> None:
    app = build_test_app()
    csv_bytes = b"id,name,email\n1,Alice,alice@acme.com\n2,Bob,bob@acme.com\n"
    json_bytes = b'[{"id": "10", "company": "Northwind LLC"}]'

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        csv_res = await client.post(
            "/api/v1/connectors/ingest/file",
            files={"file": ("customers.csv", csv_bytes, "text/csv")},
        )
        assert csv_res.status_code == 200
        assert csv_res.json()["format"] == "csv"
        assert csv_res.json()["row_count"] == 2
        assert csv_res.json()["columns"] == ["id", "name", "email"]

        json_res = await client.post(
            "/api/v1/connectors/ingest/file",
            files={"file": ("orgs.json", json_bytes, "application/json")},
        )
        assert json_res.status_code == 200
        assert json_res.json()["format"] == "json"
        assert json_res.json()["records"][0]["company"] == "Northwind LLC"
