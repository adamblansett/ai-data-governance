from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.pii.detector import scrub_for_cloud


@dataclass(frozen=True)
class LLMResponse:
    """Structured response from the local-first LLM router."""

    provider: str
    model: str
    text: str
    pii_redacted: bool
    redacted_entity_count: int
    fallback_used: bool


class LLMRouter:
    """Routes governance prompts across mock, local Ollama, and guarded cloud Gemini."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def provider_chain(self) -> list[str]:
        """Return deduplicated ordered provider chain starting with default provider."""
        ordered = [
            self.settings.llm_default_provider.lower(),
            *self.settings.fallback_provider_list,
        ]
        seen: list[str] = []
        for provider in ordered:
            if provider in {"mock", "ollama", "gemini"} and provider not in seen:
                seen.append(provider)
        return seen or ["mock"]

    def prepare_cloud_prompt(self, prompt: str) -> tuple[str, int]:
        """Redact sensitive PII spans before transmitting text to cloud LLM providers."""
        if not self.settings.llm_redact_pii_for_cloud:
            return prompt, 0
        return scrub_for_cloud(prompt)

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        task_hint: str = "governance",
    ) -> LLMResponse:
        """Generate guidance using the configured provider chain with safe fallbacks."""
        chain = self.provider_chain()
        for idx, provider in enumerate(chain):
            fallback_used = idx > 0
            if provider == "mock":
                return self._call_mock(prompt, task_hint=task_hint, fallback_used=fallback_used)
            if provider == "ollama":
                result = await self._call_ollama(
                    prompt,
                    system_prompt=system_prompt,
                    fallback_used=fallback_used,
                )
                if result is not None:
                    return result
            elif provider == "gemini":
                result = await self._call_gemini(
                    prompt,
                    system_prompt=system_prompt,
                    fallback_used=fallback_used,
                )
                if result is not None:
                    return result

        raise RuntimeError("All configured LLM providers failed to produce a response.")

    def _call_mock(
        self,
        prompt: str,
        *,
        task_hint: str,
        fallback_used: bool,
    ) -> LLMResponse:
        if task_hint == "dedup":
            text = (
                "Entity resolution prioritized deterministic identifiers (email, phone) alongside "
                "fuzzy name matching; verify golden-record survivorship before applying merges."
            )
        elif task_hint == "schema_audit":
            text = (
                "Prioritize remediating orphaned foreign keys and missing primary keys first, "
                "followed by concurrent FK indexing and retention enforcement."
            )
        elif task_hint == "normalizers":
            text = (
                "Non-destructive canonical normalization prepared; inspect flagged invalid cells "
                "prior to human approval."
            )
        else:
            snippet = " ".join(prompt.split())[:120]
            text = f"Deterministic governance guidance ({task_hint}): {snippet}"

        return LLMResponse(
            provider="mock",
            model="deterministic-mock-v1",
            text=text,
            pii_redacted=False,
            redacted_entity_count=0,
            fallback_used=fallback_used,
        )

    async def _call_ollama(
        self,
        prompt: str,
        *,
        system_prompt: str,
        fallback_used: bool,
    ) -> LLMResponse | None:
        base_url = self.settings.ollama_base_url.rstrip("/")
        url = f"{base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": self.settings.ollama_default_model,
            "prompt": f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
            if response.status_code != 200:
                return None
            data = response.json()
            text = str(data.get("response", "")).strip()
            if not text:
                return None
            return LLMResponse(
                provider="ollama",
                model=self.settings.ollama_default_model,
                text=text,
                pii_redacted=False,
                redacted_entity_count=0,
                fallback_used=fallback_used,
            )
        except Exception:
            return None

    async def _call_gemini(
        self,
        prompt: str,
        *,
        system_prompt: str,
        fallback_used: bool,
    ) -> LLMResponse | None:
        if not self.settings.gemini_api_key.strip():
            return None

        clean_prompt, prompt_redactions = self.prepare_cloud_prompt(prompt)
        clean_system, system_redactions = self.prepare_cloud_prompt(system_prompt)
        total_redactions = prompt_redactions + system_redactions
        redacted_flag = self.settings.llm_redact_pii_for_cloud and total_redactions > 0

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.gemini_default_model}:generateContent"
        )
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": clean_prompt}]}],
        }
        if clean_system:
            body["systemInstruction"] = {"parts": [{"text": clean_system}]}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-goog-api-key": self.settings.gemini_api_key,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            if response.status_code != 200:
                return None
            data = response.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            parts = candidates[0].get("content", {}).get("parts", [])
            text = " ".join(str(part.get("text", "")) for part in parts).strip()
            if not text:
                return None
            return LLMResponse(
                provider="gemini",
                model=self.settings.gemini_default_model,
                text=text,
                pii_redacted=redacted_flag,
                redacted_entity_count=total_redactions,
                fallback_used=fallback_used,
            )
        except Exception:
            return None
