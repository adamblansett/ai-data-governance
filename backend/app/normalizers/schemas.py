from typing import Any, Literal

from pydantic import BaseModel, Field

NormalizerKind = Literal[
    "email",
    "phone",
    "address",
    "taxonomy",
    "nulls",
    "whitespace",
    "date_iso",
]


class FieldRule(BaseModel):
    """Canonical normalization rule applied to a target field across records."""

    field: str = Field(min_length=1, max_length=64)
    kind: NormalizerKind
    default_country_code: str = Field(default="+1", min_length=2, max_length=6)
    taxonomy_map: dict[str, str] | None = None


class CellChange(BaseModel):
    """Per-cell transformation diff and validation outcome."""

    record_index: int
    record_id: str
    field: str
    kind: NormalizerKind
    original: Any
    normalized: Any
    valid: bool
    issue: str | None = None


class NormalizerPreviewRequest(BaseModel):
    """Input payload for non-destructive normalization preview."""

    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    rules: list[FieldRule] = Field(min_length=1, max_length=100)
    id_field: str = Field(default="id", min_length=1, max_length=64)


class NormalizerPreviewResponse(BaseModel):
    """Non-destructive diff preview and validation summary."""

    total_records: int
    changed_cells: int
    invalid_cells: int
    changes: list[CellChange]
    normalized_records: list[dict[str, Any]]


class NormalizerProposeRequest(BaseModel):
    """Request to stage normalization transforms as an HITL proposal."""

    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    rules: list[FieldRule] = Field(min_length=1, max_length=100)
    id_field: str = Field(default="id", min_length=1, max_length=64)
    title: str = Field(
        default="Bulk database field normalization",
        min_length=1,
        max_length=200,
    )
    created_by: str = Field(default="normalizer-agent", min_length=1, max_length=120)
    connector_id: str | None = None
    target_table: str | None = None
