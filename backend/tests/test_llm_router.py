from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.llm.router import LLMRouter


@pytest.mark.asyncio
async def test_llm_router_mock_mode_is_deterministic() -> None:
    router = LLMRouter(Settings(llm_default_provider="mock"))
    res = await router.generate("Summarize schema findings", task_hint="schema_audit")
    assert res.provider == "mock"
    assert res.fallback_used is False
    assert "orphaned foreign keys" in res.text


@pytest.mark.asyncio
async def test_llm_router_redacts_pii_before_cloud_call(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Cloud guidance completed safely."}]}}
                ]
            }

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            captured["json"] = kwargs.get("json")
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    settings = Settings(
        llm_default_provider="gemini",
        gemini_api_key="test-gemini-key",
        llm_redact_pii_for_cloud=True,
    )
    router = LLMRouter(settings)
    raw_prompt = (
        "Analyze customer alice@acme.com with SSN 123-45-6789 "
        "and card 4532-0151-1283-0366."
    )
    res = await router.generate(raw_prompt, task_hint="pii")

    sent_text = captured["json"]["contents"][0]["parts"][0]["text"]
    assert "alice@acme.com" not in sent_text
    assert "123-45-6789" not in sent_text
    assert "4532-0151-1283-0366" not in sent_text
    assert "[REDACTED_EMAIL]" in sent_text
    assert "[REDACTED_SSN]" in sent_text
    assert "[REDACTED_CREDIT_CARD]" in sent_text
    assert res.provider == "gemini"
    assert res.pii_redacted is True
    assert res.redacted_entity_count == 3


@pytest.mark.asyncio
async def test_llm_router_falls_back_from_ollama_and_unconfigured_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FailingAsyncClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("ollama offline")

    monkeypatch.setattr(httpx, "AsyncClient", _FailingAsyncClient)

    settings = Settings(
        llm_default_provider="ollama",
        llm_fallback_providers="gemini,mock",
        gemini_api_key="",
    )
    router = LLMRouter(settings)
    res = await router.generate("Inspect duplicate cluster", task_hint="dedup")
    assert res.provider == "mock"
    assert res.fallback_used is True
