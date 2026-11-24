from copy import deepcopy

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import build_test_app


@pytest.mark.asyncio
async def test_normalizers_preview_is_non_destructive_and_flags_invalid_cells() -> None:
    app = build_test_app()
    original_records = [
        {
            "id": "r1",
            "email": "  ALICE@Acme.COM ",
            "phone": "(415) 555-0199",
            "address": "123 main street, austin, texas 78701",
            "country": "United States",
            "notes": "N/A",
            "bio": "  Senior   Data   Engineer  ",
            "signup_date": "Nov 24, 2026",
        },
        {
            "id": "r2",
            "email": "not-an-email",
            "phone": "123",
            "address": "450 oak avenue, new york, ny 10001",
            "country": "Mars",
            "notes": "null",
            "bio": "Analyst",
            "signup_date": "bad-date",
        },
    ]
    snapshot = deepcopy(original_records)

    rules = [
        {"field": "email", "kind": "email"},
        {"field": "phone", "kind": "phone", "default_country_code": "+1"},
        {"field": "address", "kind": "address"},
        {
            "field": "country",
            "kind": "taxonomy",
            "taxonomy_map": {"united states": "US", "canada": "CA"},
        },
        {"field": "notes", "kind": "nulls"},
        {"field": "bio", "kind": "whitespace"},
        {"field": "signup_date", "kind": "date_iso"},
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/v1/normalizers/preview",
            json={"records": original_records, "rules": rules},
        )
        assert res.status_code == 200
        assert original_records == snapshot

        data = res.json()
        norm = data["normalized_records"]
        assert norm[0]["email"] == "alice@acme.com"
        assert norm[0]["phone"] == "+14155550199"
        assert norm[0]["address"] == "123 Main St, Austin, TX 78701"
        assert norm[0]["country"] == "US"
        assert norm[0]["notes"] is None
        assert norm[0]["bio"] == "Senior Data Engineer"
        assert norm[0]["signup_date"] == "2026-11-24"

        assert norm[1]["notes"] is None
        assert data["invalid_cells"] == 4  # bad email, phone, taxonomy ('Mars'), date

        propose_res = await client.post(
            "/api/v1/normalizers/propose",
            json={
                "records": original_records,
                "rules": rules,
                "title": "Normalize CRM import batch",
            },
        )
        assert propose_res.status_code == 200
        proposal = propose_res.json()
        assert proposal["domain"] == "normalizers"
        assert proposal["status"] == "pending_review"
        assert proposal["before_snapshot"] == original_records
