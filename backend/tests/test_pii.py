import pytest
from httpx import ASGITransport, AsyncClient

from app.pii.detector import iban_valid, luhn_valid
from tests.conftest import build_test_app


@pytest.mark.asyncio
async def test_pii_scan_regex_checksums_and_ner() -> None:
    app = build_test_app()
    sample = (
        "Contact Dr. Elena Vance at elena.vance@northwind.io or (415) 555-0199. "
        "SSN: 123-45-6789, Card: 4532-0151-1283-0366, IBAN: GB82WEST12345698765432, "
        "InvalidCard: 4532-0151-1283-0367, API: sk-testkey1234567890abcdef, "
        "IP: 192.168.10.25, Org: Northwind Health LLC, Addr: 742 Evergreen Ave."
    )
    assert luhn_valid("4532015112830366") is True
    assert luhn_valid("4532015112830367") is False
    assert iban_valid("GB82WEST12345698765432") is True
    assert iban_valid("GB00WEST12345698765432") is False

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/pii/scan", json={"text": sample, "include_ner": True})
        assert resp.status_code == 200
        data = resp.json()
        counts = data["entity_counts"]
        assert counts["EMAIL"] == 1
        assert counts["SSN"] == 1
        assert counts["CREDIT_CARD"] == 1  # invalid Luhn card excluded
        assert counts["IBAN"] == 1
        assert counts["API_KEY"] == 1
        assert counts["IP_ADDRESS"] == 1
        assert counts["PHONE"] == 1
        assert counts["PERSON"] == 1
        assert counts["ORG"] == 1
        assert counts["LOCATION"] == 1
        assert data["risk_level"] == "high"
        assert "123-45-6789" not in str(data)


@pytest.mark.asyncio
async def test_pii_masking_strategies_vault_detokenize_and_audit() -> None:
    app = build_test_app()
    raw_email = "alice.mercer@acme.com"
    raw_ssn = "123-45-6789"
    records = [
        {"name": "Alice Mercer", "email": raw_email, "ssn": raw_ssn},
        {"name": "Bob Stone", "email": raw_email, "ssn": "987-65-4321"},
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for strategy in ("redact", "mask", "hash"):
            res = await client.post(
                "/api/v1/pii/mask",
                json={"text": f"User {raw_email} SSN {raw_ssn}", "strategy": strategy},
            )
            assert res.status_code == 200
            masked_text = res.json()["masked_text"]
            assert raw_email not in masked_text
            assert raw_ssn not in masked_text

        tok_res = await client.post(
            "/api/v1/pii/mask",
            json={"records": records, "strategy": "tokenize", "policy_name": "hr-strict"},
        )
        assert tok_res.status_code == 200
        tok_data = tok_res.json()
        masked_records = tok_data["masked_records"]
        # Idempotent vault tokenization reuses exact same token for duplicate plaintext email
        assert masked_records[0]["email"] == masked_records[1]["email"]
        assert masked_records[0]["email"].startswith("TOK_EMAIL_")
        assert raw_ssn not in str(masked_records)

        stats_res = await client.get("/api/v1/pii/vault/stats")
        assert stats_res.status_code == 200
        stats = stats_res.json()
        assert stats["total_tokens"] == len(tok_data["tokens_created"])
        assert raw_email not in str(stats)
        assert raw_ssn not in str(stats)

        email_token = masked_records[0]["email"]
        ssn_token = masked_records[0]["ssn"]
        detok_res = await client.post(
            "/api/v1/pii/detokenize",
            json={
                "tokens": [email_token, ssn_token, "TOK_EMAIL_DOESNOTEXIST"],
                "actor": "privacy-officer",
                "reason": "DSAR export verification",
            },
        )
        assert detok_res.status_code == 200
        detok_data = detok_res.json()
        assert detok_data["resolved"][email_token] == raw_email
        assert detok_data["resolved"][ssn_token] == raw_ssn
        assert detok_data["missing_tokens"] == ["TOK_EMAIL_DOESNOTEXIST"]

        audit_res = await client.get("/api/v1/governance/audit?domain=pii")
        assert audit_res.status_code == 200
        audit_payload = audit_res.text
        assert raw_email not in audit_payload
        assert raw_ssn not in audit_payload
