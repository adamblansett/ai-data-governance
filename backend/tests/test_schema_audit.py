import pytest
from httpx import ASGITransport, AsyncClient

from app.schema_audit.analyzer import parse_postgres_ddl
from tests.conftest import build_test_app


def test_parse_postgres_ddl_extracts_tables_fks_and_indexes() -> None:
    ddl = """
    CREATE TABLE customers (
        id BIGINT PRIMARY KEY,
        email TEXT NOT NULL,
        ssn TEXT,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE orders (
        order_id BIGINT PRIMARY KEY,
        customer_id BIGINT REFERENCES customers(id),
        total NUMERIC(10, 2)
    );
    CREATE INDEX idx_orders_total ON orders (total);
    """
    tables = parse_postgres_ddl(ddl)
    assert len(tables) == 2
    orders = next(t for t in tables if t.name == "orders")
    assert orders.primary_key == ["order_id"]
    assert len(orders.foreign_keys) == 1
    assert orders.foreign_keys[0].column == "customer_id"
    assert orders.foreign_keys[0].ref_table == "customers"
    assert len(orders.indexes) == 1
    assert orders.indexes[0].name == "idx_orders_total"


@pytest.mark.asyncio
async def test_schema_audit_detects_all_hygiene_categories_and_proposes_remediation() -> None:
    app = build_test_app()
    ddl = """
    CREATE TABLE users (
        id BIGINT PRIMARY KEY,
        email TEXT NOT NULL,
        ssn TEXT,
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE TABLE audit_scratch (
        event_payload TEXT
    );
    CREATE TABLE invoices (
        id BIGINT PRIMARY KEY,
        user_id BIGINT REFERENCES users(id),
        legacy_org_id BIGINT REFERENCES missing_orgs(id),
        created_at TIMESTAMPTZ NOT NULL
    );
    CREATE INDEX idx_invoices_unused ON invoices (created_at);
    """
    catalog_tables = [
        {
            "name": "users",
            "row_count": 50000,
            "seq_scans": 2400,
            "idx_scans": 120,
            "retention_days": 90,
            "oldest_record_days": 410,
        },
        {
            "name": "invoices",
            "row_count": 25000,
            "foreign_keys": [
                {"column": "user_id", "ref_table": "users", "ref_column": "id", "orphan_count": 14},
                {"column": "legacy_org_id", "ref_table": "missing_orgs", "ref_column": "id"},
            ],
            "indexes": [
                {"name": "idx_invoices_unused", "columns": ["created_at"], "scans": 0}
            ],
        },
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/schema-audit/analyze",
            json={"ddl_sql": ddl, "tables": catalog_tables, "default_retention_days": 365},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["tables_analyzed"] == 3
        assert data["health_score"] < 50.0
        categories = {f["category"] for f in data["findings"]}
        assert {
            "missing_pk",
            "orphaned_fk",
            "unindexed_fk",
            "query_hotspot",
            "retention_policy",
            "pii_column_risk",
            "unused_index",
        }.issubset(categories)

        prop_res = await client.post(
            "/api/v1/schema-audit/propose-remediation",
            json={"findings": data["findings"], "title": "Apply schema fixes"},
        )
        assert prop_res.status_code == 200
        proposal = prop_res.json()
        assert proposal["domain"] == "schema_audit"
        assert proposal["status"] == "pending_review"
        assert len(proposal["payload"]["statements"]) >= 5
