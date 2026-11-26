from typing import Any, Literal

from pydantic import BaseModel, Field

SurvivorshipRule = Literal[
    "most_complete",
    "most_recent",
    "longest",
    "prefer_first",
    "prefer_non_null",
]


class DedupAnalyzeRequest(BaseModel):
    """Input payload for blocking, fuzzy scoring, and golden-record clustering."""

    records: list[dict[str, Any]] = Field(min_length=2, max_length=500)
    id_field: str = Field(default="id", min_length=1, max_length=64)
    updated_at_field: str = Field(default="updated_at", min_length=1, max_length=64)
    threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    weights: dict[str, float] | None = None
    survivorship: SurvivorshipRule = "most_complete"
    field_survivorship: dict[str, SurvivorshipRule] | None = None


class PairMatch(BaseModel):
    """Similarity breakdown for a candidate duplicate pair."""

    record_a_id: str
    record_b_id: str
    similarity: float
    blocking_keys: list[str]
    field_scores: dict[str, float]


class DuplicateCluster(BaseModel):
    """Cluster of duplicate records with proposed golden record and field provenance."""

    cluster_id: str
    record_ids: list[str]
    records: list[dict[str, Any]]
    pair_matches: list[PairMatch]
    average_similarity: float
    golden_record: dict[str, Any]
    field_provenance: dict[str, str]


class DedupAnalyzeResponse(BaseModel):
    """Result of duplicate analysis across submitted records."""

    total_records: int
    cluster_count: int
    duplicate_record_count: int
    clusters: list[DuplicateCluster]
    ai_summary: str
    llm_provider: str


class ProposeMergeRequest(BaseModel):
    """Request to queue a human-reviewed golden-record merge proposal."""

    cluster_id: str = Field(min_length=1, max_length=64)
    source_records: list[dict[str, Any]] = Field(min_length=2)
    golden_record: dict[str, Any]
    id_field: str = Field(default="id", min_length=1, max_length=64)
    rationale: str = Field(
        default="Fuzzy entity resolution cluster merge",
        max_length=1000,
    )
    created_by: str = Field(default="dedup-agent", min_length=1, max_length=120)
    connector_id: str | None = None
    target_table: str | None = None
