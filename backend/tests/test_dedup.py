import pytest
from httpx import ASGITransport, AsyncClient

from app.dedup.engine import analyze_clusters
from tests.conftest import build_test_app


def test_dedup_engine_fuzzy_clustering_and_survivorship_rules() -> None:
    records = [
        {
            "id": "c-1",
            "name": "Jane Doe",
            "email": "jane.doe@acme.com",
            "phone": "(555) 234-5678",
            "company": "Acme",
            "updated_at": "2026-01-10T00:00:00Z",
        },
        {
            "id": "c-2",
            "name": "Doe, Jane",
            "email": "jane.doe@acme.com",
            "phone": "+1-555-234-5678",
            "company": "Acme Corporation",
            "notes": "Enterprise buyer",
            "updated_at": "2026-05-12T00:00:00Z",
        },
        {
            "id": "c-3",
            "name": "Marcus Vance",
            "email": "marcus@globex.io",
            "phone": "555-999-0000",
            "company": "Globex",
            "updated_at": "2026-03-01T00:00:00Z",
        },
    ]

    clusters_complete = analyze_clusters(records, threshold=0.78, survivorship="most_complete")
    assert len(clusters_complete) == 1
    c = clusters_complete[0]
    assert c.record_ids == ["c-1", "c-2"]
    assert c.golden_record["id"] == "c-2"
    assert c.golden_record["notes"] == "Enterprise buyer"
    assert c.field_provenance["notes"] == "c-2"

    clusters_longest = analyze_clusters(
        records,
        threshold=0.78,
        survivorship="most_recent",
        field_survivorship={"company": "longest"},
    )
    assert clusters_longest[0].golden_record["company"] == "Acme Corporation"
    assert clusters_longest[0].field_provenance["company"] == "c-2"


@pytest.mark.asyncio
async def test_dedup_api_analyze_and_propose_merge() -> None:
    app = build_test_app()
    records = [
        {"id": "101", "name": "Alicia Smith", "email": "alice@northwind.io"},
        {"id": "102", "name": "Alice Smith", "email": "alice@northwind.io", "tier": "pro"},
        {"id": "103", "name": "Devon Brooks", "email": "devon@other.org"},
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        analyze_res = await client.post(
            "/api/v1/dedup/analyze",
            json={"records": records, "threshold": 0.78, "survivorship": "most_complete"},
        )
        assert analyze_res.status_code == 200
        analyzed = analyze_res.json()
        assert analyzed["cluster_count"] == 1
        assert analyzed["duplicate_record_count"] == 2
        assert analyzed["llm_provider"] == "mock"
        cluster = analyzed["clusters"][0]

        prop_res = await client.post(
            "/api/v1/dedup/propose-merge",
            json={
                "cluster_id": cluster["cluster_id"],
                "source_records": cluster["records"],
                "golden_record": cluster["golden_record"],
                "rationale": "Verified duplicate customer entity",
            },
        )
        assert prop_res.status_code == 200
        proposal = prop_res.json()
        assert proposal["domain"] == "dedup"
        assert proposal["status"] == "pending_review"
        assert proposal["risk_level"] == "high"
        assert len(proposal["before_snapshot"]) == 2
