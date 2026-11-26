from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.dedup.schemas import SurvivorshipRule

ConnectorType = Literal["sqlite", "postgresql"]


class ConnectorCreateRequest(BaseModel):
    """Request to register a new database connector with encrypted DSN."""

    name: str = Field(min_length=1, max_length=120)
    connector_type: ConnectorType
    dsn: str = Field(min_length=5, max_length=1024)
    read_only: bool = True
    description: str = Field(default="", max_length=500)


class ConnectorResponse(BaseModel):
    """Registered database connector summary (never exposes raw DSN)."""

    id: str
    name: str
    connector_type: str
    dsn_masked: str
    read_only: bool
    description: str
    created_by: str
    created_at: datetime


class ConnectorTestResponse(BaseModel):
    """Live database connectivity diagnostic result."""

    connector_id: str
    name: str
    connector_type: str
    ok: bool
    dialect: str
    latency_ms: float
    table_count: int
    error: str | None = None


class ConnectorSampleResponse(BaseModel):
    """Bounded sample rows retrieved from a live database table."""

    connector_id: str
    table_name: str
    row_count_sampled: int
    columns: list[str]
    rows: list[dict[str, Any]]


class ConnectorAuditRequest(BaseModel):
    """Options for running schema hygiene audit on a live connector."""

    default_retention_days: int = Field(default=365, ge=1, le=36500)


class ConnectorPiiScanRequest(BaseModel):
    """Options for sampling and scanning a live table for PII."""

    limit: int = Field(default=100, ge=1, le=500)
    policy_name: str = Field(default="default", min_length=1, max_length=64)
    include_ner: bool = True


class ConnectorDedupRequest(BaseModel):
    """Options for sampling and analyzing duplicates in a live table."""

    limit: int = Field(default=100, ge=2, le=500)
    id_field: str = Field(default="id", min_length=1, max_length=64)
    threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    survivorship: SurvivorshipRule = "most_complete"


class FileIngestResponse(BaseModel):
    """Parsed records and column metadata from an uploaded CSV or JSON file."""

    filename: str
    format: Literal["csv", "json"]
    row_count: int
    columns: list[str]
    records: list[dict[str, Any]]
