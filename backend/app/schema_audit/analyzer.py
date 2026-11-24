import re

from app.schema_audit.schemas import (
    ColumnMeta,
    FindingSeverity,
    ForeignKeyMeta,
    IndexMeta,
    SchemaFinding,
    TableMeta,
)

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_CREATE_TABLE_START_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[\w\"]+\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*\(",
    re.IGNORECASE,
)
_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s+ON\s+(?:[\w\"]+\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?"
    r"(?:\s+USING\s+\w+)?\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_TABLE_PK_RE = re.compile(
    r"^(?:CONSTRAINT\s+\"?[A-Za-z0-9_]+\"?\s+)?PRIMARY\s+KEY\s*\(([^)]+)\)",
    re.IGNORECASE,
)
_TABLE_FK_RE = re.compile(
    r"^(?:CONSTRAINT\s+\"?[A-Za-z0-9_]+\"?\s+)?FOREIGN\s+KEY\s*\(\"?([A-Za-z_][A-Za-z0-9_]*)\"?\)"
    r"\s+REFERENCES\s+(?:[\w\"]+\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*"
    r"(?:\(\"?([A-Za-z_][A-Za-z0-9_]*)\"?\))?",
    re.IGNORECASE,
)
_INLINE_REF_RE = re.compile(
    r"REFERENCES\s+(?:[\w\"]+\.)?\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s*"
    r"(?:\(\"?([A-Za-z_][A-Za-z0-9_]*)\"?\))?",
    re.IGNORECASE,
)

_HIGH_RISK_PII_KEYWORDS = (
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "iban",
    "passport",
)
_PII_KEYWORDS = (
    *_HIGH_RISK_PII_KEYWORDS,
    "email",
    "phone",
    "mobile",
    "dob",
    "birth_date",
    "address",
    "street_address",
    "ip_address",
)
_TIMESTAMP_COLUMN_NAMES = {
    "created_at",
    "updated_at",
    "logged_at",
    "event_time",
    "timestamp",
    "recorded_at",
    "occurred_at",
}
_SEVERITY_PENALTY: dict[FindingSeverity, float] = {
    "critical": 22.0,
    "high": 14.0,
    "medium": 7.0,
    "low": 3.0,
}


def _strip_comments(sql: str) -> str:
    without_block = _BLOCK_COMMENT_RE.sub(" ", sql)
    return _LINE_COMMENT_RE.sub(" ", without_block)


def _split_top_level_csv(body: str) -> list[str]:
    items: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    current: list[str] = []

    for ch in body:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                part = "".join(current).strip()
                if part:
                    items.append(part)
                current = []
                continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _extract_balanced_body(sql: str, open_paren_idx: int) -> tuple[str, int] | None:
    depth = 0
    in_single = False
    in_double = False
    for idx in range(open_paren_idx, len(sql)):
        ch = sql[idx]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return sql[open_paren_idx + 1 : idx], idx + 1
    return None


def parse_postgres_ddl(ddl_sql: str) -> list[TableMeta]:
    """Parse PostgreSQL CREATE TABLE and CREATE INDEX DDL statements into TableMeta."""
    clean_sql = _strip_comments(ddl_sql)
    tables: dict[str, TableMeta] = {}

    pos = 0
    while True:
        match = _CREATE_TABLE_START_RE.search(clean_sql, pos)
        if match is None:
            break
        table_name = match.group(1)
        open_paren_idx = match.end() - 1
        extracted = _extract_balanced_body(clean_sql, open_paren_idx)
        if extracted is None:
            break
        body, next_pos = extracted
        pos = next_pos

        columns: list[ColumnMeta] = []
        primary_key: list[str] = []
        foreign_keys: list[ForeignKeyMeta] = []

        for item in _split_top_level_csv(body):
            pk_match = _TABLE_PK_RE.match(item)
            if pk_match:
                cols = [c.strip().strip('"') for c in pk_match.group(1).split(",") if c.strip()]
                primary_key.extend(cols)
                continue

            fk_match = _TABLE_FK_RE.match(item)
            if fk_match:
                foreign_keys.append(
                    ForeignKeyMeta(
                        column=fk_match.group(1),
                        ref_table=fk_match.group(2),
                        ref_column=fk_match.group(3) or "id",
                    )
                )
                continue

            if re.match(r"^(?:CONSTRAINT|UNIQUE|CHECK|EXCLUDE)\b", item, re.IGNORECASE):
                continue

            tokens = item.split(None, 2)
            if len(tokens) < 2:
                continue
            col_name = tokens[0].strip('"')
            col_type = tokens[1]
            rest = tokens[2] if len(tokens) > 2 else ""

            is_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", item, re.IGNORECASE))
            not_null = is_pk or bool(re.search(r"\bNOT\s+NULL\b", item, re.IGNORECASE))
            if is_pk and col_name not in primary_key:
                primary_key.append(col_name)

            columns.append(
                ColumnMeta(
                    name=col_name,
                    data_type=col_type,
                    nullable=not not_null,
                    is_primary_key=is_pk,
                )
            )

            ref_match = _INLINE_REF_RE.search(rest if rest else item)
            if ref_match:
                foreign_keys.append(
                    ForeignKeyMeta(
                        column=col_name,
                        ref_table=ref_match.group(1),
                        ref_column=ref_match.group(2) or "id",
                    )
                )

        # Ensure inline/table primary keys mark ColumnMeta.is_primary_key consistently
        pk_set = {col.lower() for col in primary_key}
        for col in columns:
            if col.name.lower() in pk_set:
                col.is_primary_key = True

        tables[table_name.lower()] = TableMeta(
            name=table_name,
            columns=columns,
            primary_key=primary_key,
            foreign_keys=foreign_keys,
        )

    for idx_match in _CREATE_INDEX_RE.finditer(clean_sql):
        is_unique = bool(idx_match.group(1))
        idx_name = idx_match.group(2)
        target_table = idx_match.group(3)
        raw_cols = idx_match.group(4)
        idx_cols = [
            part.strip().split()[0].strip('"')
            for part in raw_cols.split(",")
            if part.strip()
        ]
        table = tables.get(target_table.lower())
        if table is None:
            table = TableMeta(name=target_table)
            tables[target_table.lower()] = table
        table.indexes.append(IndexMeta(name=idx_name, columns=idx_cols, unique=is_unique))

    return list(tables.values())


def merge_tables(ddl_tables: list[TableMeta], explicit_tables: list[TableMeta]) -> list[TableMeta]:
    """Merge DDL-parsed tables with structured catalog metadata."""
    merged: dict[str, TableMeta] = {t.name.lower(): t for t in ddl_tables}
    for table in explicit_tables:
        key = table.name.lower()
        existing = merged.get(key)
        if existing is None:
            merged[key] = table
            continue
        if table.columns:
            existing.columns = table.columns
        if table.primary_key:
            existing.primary_key = table.primary_key
        if table.foreign_keys:
            existing.foreign_keys = table.foreign_keys
        if table.indexes:
            existing.indexes = table.indexes
        existing.row_count = max(existing.row_count, table.row_count)
        existing.seq_scans = max(existing.seq_scans, table.seq_scans)
        existing.idx_scans = max(existing.idx_scans, table.idx_scans)
        if table.retention_days is not None:
            existing.retention_days = table.retention_days
        if table.oldest_record_days is not None:
            existing.oldest_record_days = table.oldest_record_days
    return list(merged.values())


def _is_pii_column(name: str) -> tuple[bool, FindingSeverity]:
    low = name.lower()
    if any(kw in low for kw in _HIGH_RISK_PII_KEYWORDS):
        return True, "high"
    if any(kw in low for kw in _PII_KEYWORDS):
        return True, "medium"
    return False, "medium"


def _find_timestamp_column(table: TableMeta) -> str | None:
    for col in table.columns:
        low = col.name.lower()
        if low in _TIMESTAMP_COLUMN_NAMES or "timestamp" in col.data_type.lower():
            return col.name
    return None


def audit_schema(
    tables: list[TableMeta],
    *,
    default_retention_days: int = 365,
) -> tuple[list[SchemaFinding], float]:
    """Audit schema catalog metadata for integrity, indexing, PII, and retention hygiene."""
    table_map: dict[str, TableMeta] = {t.name.lower(): t for t in tables}
    findings: list[SchemaFinding] = []
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"finding-{counter}"

    for table in tables:
        pk_cols = list(table.primary_key) or [c.name for c in table.columns if c.is_primary_key]
        if not pk_cols:
            findings.append(
                SchemaFinding(
                    finding_id=_next_id(),
                    category="missing_pk",
                    severity="high",
                    table=table.name,
                    title=f"Missing primary key on '{table.name}'",
                    description=(
                        f"Table '{table.name}' has no primary key constraint, preventing "
                        "deterministic row identity, replication safety, and deduplication."
                    ),
                    recommendation="Add a surrogate IDENTITY primary key or composite natural PK.",
                    remediation_sql=(
                        f"ALTER TABLE {table.name} "
                        "ADD COLUMN id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY;"
                    ),
                )
            )

        leading_indexed = {
            idx.columns[0].lower() for idx in table.indexes if idx.columns
        }
        if len(pk_cols) == 1:
            leading_indexed.add(pk_cols[0].lower())

        for fk in table.foreign_keys:
            ref_table = table_map.get(fk.ref_table.lower())
            ref_col_exists = True
            if ref_table is not None and ref_table.columns:
                ref_col_names = {c.name.lower() for c in ref_table.columns}
                ref_col_exists = fk.ref_column.lower() in ref_col_names

            if ref_table is None or not ref_col_exists:
                reason = (
                    f"Referenced table '{fk.ref_table}' is missing from catalog"
                    if ref_table is None
                    else f"Referenced column '{fk.ref_table}.{fk.ref_column}' does not exist"
                )
                findings.append(
                    SchemaFinding(
                        finding_id=_next_id(),
                        category="orphaned_fk",
                        severity="critical",
                        table=table.name,
                        column=fk.column,
                        title=f"Broken foreign key target on '{table.name}.{fk.column}'",
                        description=f"{reason}.",
                        recommendation=(
                            "Restore the missing parent relation or drop/quarantine the broken FK."
                        ),
                        remediation_sql=(
                            f"ALTER TABLE {table.name} "
                            f"DROP CONSTRAINT IF EXISTS fk_{table.name}_{fk.column};"
                        ),
                    )
                )
            elif fk.orphan_count > 0:
                findings.append(
                    SchemaFinding(
                        finding_id=_next_id(),
                        category="orphaned_fk",
                        severity="critical",
                        table=table.name,
                        column=fk.column,
                        title=f"{fk.orphan_count} orphaned rows in '{table.name}.{fk.column}'",
                        description=(
                            f"Found {fk.orphan_count} rows in '{table.name}' referencing "
                            f"missing '{fk.ref_table}.{fk.ref_column}' records."
                        ),
                        recommendation="Quarantine orphan records before re-enabling strict FK.",
                        remediation_sql=(
                            f"CREATE TABLE IF NOT EXISTS {table.name}_orphans AS "
                            f"SELECT t.* FROM {table.name} t "
                            f"LEFT JOIN {fk.ref_table} r ON r.{fk.ref_column} = t.{fk.column} "
                            f"WHERE t.{fk.column} IS NOT NULL AND r.{fk.ref_column} IS NULL;\n"
                            f"DELETE FROM {table.name} t "
                            f"WHERE t.{fk.column} IS NOT NULL AND NOT EXISTS ("
                            f"SELECT 1 FROM {fk.ref_table} r "
                            f"WHERE r.{fk.ref_column} = t.{fk.column}"
                            ");"
                        ),
                    )
                )

            if fk.column.lower() not in leading_indexed:
                findings.append(
                    SchemaFinding(
                        finding_id=_next_id(),
                        category="unindexed_fk",
                        severity="high",
                        table=table.name,
                        column=fk.column,
                        title=f"Unindexed foreign key '{table.name}.{fk.column}'",
                        description=(
                            f"Foreign key '{fk.column}' lacks a leading B-tree index, causing "
                            "sequential scans on joins and parent deletes."
                        ),
                        recommendation=(
                            "Create a concurrent B-tree index on the foreign key column."
                        ),
                        remediation_sql=(
                            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                            f"idx_{table.name}_{fk.column} ON {table.name} ({fk.column});"
                        ),
                    )
                )

        if (
            table.row_count >= 10_000
            and table.seq_scans > 100
            and table.seq_scans > table.idx_scans * 5
        ):
            findings.append(
                SchemaFinding(
                    finding_id=_next_id(),
                    category="query_hotspot",
                    severity="high",
                    table=table.name,
                    title=f"Sequential scan hotspot on '{table.name}'",
                    description=(
                        f"Table '{table.name}' ({table.row_count:,} rows) recorded "
                        f"{table.seq_scans:,} sequential scans vs {table.idx_scans:,} index scans."
                    ),
                    recommendation=(
                        "Inspect top filter predicates with EXPLAIN ANALYZE "
                        "and add targeted indexes."
                    ),
                    remediation_sql=(
                        f"ANALYZE {table.name};\n"
                        "-- Review filter columns in pg_stat_statements before adding index:\n"
                        f"-- CREATE INDEX CONCURRENTLY idx_{table.name}_hot "
                        f"ON {table.name} (<filter_col>);"
                    ),
                )
            )

        has_untagged_pii = False
        has_any_pii = False
        for col in table.columns:
            is_pii, pii_sev = _is_pii_column(col.name)
            if is_pii:
                has_any_pii = True
                if not col.has_pii_tag:
                    has_untagged_pii = True
                    findings.append(
                        SchemaFinding(
                            finding_id=_next_id(),
                            category="pii_column_risk",
                            severity=pii_sev,
                            table=table.name,
                            column=col.name,
                            title=f"Unclassified PII column '{table.name}.{col.name}'",
                            description=(
                                f"Column '{col.name}' appears to store sensitive personal data "
                                "without a governance PII classification tag."
                            ),
                            recommendation=(
                                "Tag the column for automated masking/tokenization "
                                "and access audit."
                            ),
                            remediation_sql=(
                                f"COMMENT ON COLUMN {table.name}.{col.name} "
                                "IS 'governance:pii_classified=true;masking_required=true';"
                            ),
                        )
                    )

        ts_col = _find_timestamp_column(table)
        if (ts_col is not None or has_any_pii) and table.retention_days is None:
            target_ts = ts_col or "created_at"
            findings.append(
                SchemaFinding(
                    finding_id=_next_id(),
                    category="retention_policy",
                    severity="medium" if not has_untagged_pii else "high",
                    table=table.name,
                    title=f"Missing data retention policy on '{table.name}'",
                    description=(
                        f"Table '{table.name}' holds time-series or PII attributes without an "
                        "explicit retention_days SLA."
                    ),
                    recommendation=(
                        f"Enforce a {default_retention_days}-day archival/purge policy."
                    ),
                    remediation_sql=(
                        f"-- Enforce {default_retention_days}-day retention policy "
                        f"on {table.name}\n"
                        f"DELETE FROM {table.name} "
                        f"WHERE {target_ts} < NOW() - INTERVAL '{default_retention_days} days';"
                    ),
                )
            )
        elif (
            table.retention_days is not None
            and table.oldest_record_days is not None
            and table.oldest_record_days > table.retention_days
        ):
            target_ts = ts_col or "created_at"
            findings.append(
                SchemaFinding(
                    finding_id=_next_id(),
                    category="retention_policy",
                    severity="high",
                    table=table.name,
                    title=f"Retention SLA violated on '{table.name}'",
                    description=(
                        f"Oldest record age ({table.oldest_record_days} days) exceeds configured "
                        f"retention policy ({table.retention_days} days)."
                    ),
                    recommendation="Archive and purge expired records beyond the retention window.",
                    remediation_sql=(
                        f"DELETE FROM {table.name} "
                        f"WHERE {target_ts} < NOW() - INTERVAL '{table.retention_days} days';"
                    ),
                )
            )

        for idx in table.indexes:
            if not idx.unique and idx.scans == 0 and table.row_count >= 10_000:
                findings.append(
                    SchemaFinding(
                        finding_id=_next_id(),
                        category="unused_index",
                        severity="low",
                        table=table.name,
                        column=idx.columns[0] if idx.columns else None,
                        title=f"Unused index '{idx.name}' on '{table.name}'",
                        description=(
                            f"Non-unique index '{idx.name}' has 0 recorded scans on a "
                            f"{table.row_count:,}-row table, adding write amplification."
                        ),
                        recommendation=(
                            "Drop unused index concurrently after verifying query plans."
                        ),
                        remediation_sql=f"DROP INDEX CONCURRENTLY IF EXISTS {idx.name};",
                    )
                )

    total_penalty = sum(_SEVERITY_PENALTY[f.severity] for f in findings)
    health_score = round(max(0.0, 100.0 - total_penalty), 1)
    return findings, health_score
