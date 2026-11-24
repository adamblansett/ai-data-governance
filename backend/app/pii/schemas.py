from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

MaskStrategy = Literal["redact", "mask", "hash", "tokenize"]


class PiiEntityMatch(BaseModel):
    """Single detected PII span with masked preview (never raw sensitive output)."""

    entity_type: str
    start: int
    end: int
    confidence: float
    source: Literal["regex", "heuristic_ner"]
    field_path: str | None = None
    masked_preview: str


class PiiScanRequest(BaseModel):
    """Input payload for PII scanning on freeform text or structured records."""

    text: str | None = None
    records: list[dict[str, Any]] | None = None
    policy_name: str = Field(default="default", min_length=1, max_length=64)
    include_ner: bool = True
    entity_types: list[str] | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> "PiiScanRequest":
        if self.text is None and self.records is None:
            raise ValueError("Provide either 'text' or 'records' for PII scanning.")
        return self


class PiiScanResponse(BaseModel):
    """Result of scanning text or structured records for PII."""

    findings: list[PiiEntityMatch]
    total_findings: int
    entity_counts: dict[str, int]
    risk_score: float
    risk_level: Literal["low", "medium", "high"]


class PiiMaskRequest(BaseModel):
    """Input payload for masking, redacting, hashing, or tokenizing PII."""

    text: str | None = None
    records: list[dict[str, Any]] | None = None
    strategy: MaskStrategy = "mask"
    policy_name: str = Field(default="default", min_length=1, max_length=64)
    include_ner: bool = True
    entity_types: list[str] | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> "PiiMaskRequest":
        if self.text is None and self.records is None:
            raise ValueError("Provide either 'text' or 'records' for PII masking.")
        return self


class PiiMaskResponse(BaseModel):
    """Result of applying a PII masking/tokenization strategy."""

    strategy: MaskStrategy
    masked_text: str | None = None
    masked_records: list[dict[str, Any]] | None = None
    findings: list[PiiEntityMatch]
    applied_count: int
    tokens_created: list[str]
    risk_score: float
    risk_level: Literal["low", "medium", "high"]


class PiiDetokenizeRequest(BaseModel):
    """Audited request to resolve reversible PII vault tokens."""

    tokens: list[str] = Field(min_length=1, max_length=200)
    actor: str = Field(default="data-steward", min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=500)


class PiiDetokenizeResponse(BaseModel):
    """Resolved plaintext mapping for authorized detokenization requests."""

    resolved: dict[str, str]
    missing_tokens: list[str]


class PiiVaultStatsResponse(BaseModel):
    """Aggregated token counts stored in the encrypted PII vault."""

    total_tokens: int
    by_entity_type: dict[str, int]
