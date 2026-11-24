from typing import Literal

from pydantic import BaseModel, Field, model_validator

FindingSeverity = Literal["low", "medium", "high", "critical"]
FindingCategory = Literal[
    "orphaned_fk",
    "unindexed_fk",
    "query_hotspot",
    "missing_pk",
    "retention_policy",
    "pii_column_risk",
    "unused_index",
]


class ColumnMeta(BaseModel):
    """Metadata description of a database column."""

    name: str
    data_type: str = "text"
    nullable: bool = True
    is_primary_key: bool = False
    has_pii_tag: bool = False


class ForeignKeyMeta(BaseModel):
    """Foreign key relationship and optional orphan diagnostic count."""

    column: str
    ref_table: str
    ref_column: str = "id"
    orphan_count: int = Field(default=0, ge=0)


class IndexMeta(BaseModel):
    """Database index definition and optional scan telemetry."""

    name: str
    columns: list[str]
    unique: bool = False
    scans: int | None = Field(default=None, ge=0)


class TableMeta(BaseModel):
    """Table schema and operational telemetry for hygiene analysis."""

    name: str
    columns: list[ColumnMeta] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyMeta] = Field(default_factory=list)
    indexes: list[IndexMeta] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    seq_scans: int = Field(default=0, ge=0)
    idx_scans: int = Field(default=0, ge=0)
    retention_days: int | None = Field(default=None, ge=1)
    oldest_record_days: int | None = Field(default=None, ge=0)


class SchemaFinding(BaseModel):
    """Actionable schema hygiene finding with optional SQL remediation."""

    finding_id: str
    category: FindingCategory
    severity: FindingSeverity
    table: str
    column: str | None = None
    title: str
    description: str
    recommendation: str
    remediation_sql: str = ""


class SchemaAuditRequest(BaseModel):
    """Input payload containing PostgreSQL DDL SQL and/or structured table catalog."""

    ddl_sql: str | None = None
    tables: list[TableMeta] = Field(default_factory=list)
    default_retention_days: int = Field(default=365, ge=1, le=36500)

    @model_validator(mode="after")
    def _validate_inputs(self) -> "SchemaAuditRequest":
        has_ddl = bool(self.ddl_sql and self.ddl_sql.strip())
        if not has_ddl and not self.tables:
            raise ValueError("Provide either 'ddl_sql' or non-empty 'tables' metadata.")
        return self


class SchemaAuditResponse(BaseModel):
    """Schema hygiene score, structured findings, and AI remediation summary."""

    tables_analyzed: int
    health_score: float
    findings_count: int
    findings_by_severity: dict[str, int]
    findings: list[SchemaFinding]
    ai_summary: str
    llm_provider: str


class ProposeRemediationRequest(BaseModel):
    """Request to queue selected schema hygiene remediations for HITL approval."""

    findings: list[SchemaFinding] = Field(min_length=1)
    title: str = Field(
        default="PostgreSQL schema hygiene remediation plan",
        min_length=1,
        max_length=200,
    )
    created_by: str = Field(default="schema-auditor", min_length=1, max_length=120)
