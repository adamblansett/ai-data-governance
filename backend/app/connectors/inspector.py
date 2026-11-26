import re
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from app.schema_audit.schemas import ColumnMeta, ForeignKeyMeta, IndexMeta, TableMeta

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIMESTAMP_HINTS = (
    "created_at",
    "updated_at",
    "logged_at",
    "event_time",
    "timestamp",
    "recorded_at",
)


def validate_ident(name: str) -> str:
    """Validate a SQL identifier against safe alphanumeric/underscore characters."""
    cleaned = name.strip()
    if not _SAFE_IDENT_RE.match(cleaned):
        raise ValueError(f"Unsafe SQL identifier rejected: '{name}'")
    return cleaned


def quote_ident(name: str) -> str:
    """Safely double-quote a validated SQL identifier."""
    return f'"{validate_ident(name)}"'


def create_connector_engine(dsn: str) -> AsyncEngine:
    """Create an async SQLAlchemy engine for an external target database."""
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if dsn.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in dsn:
            kwargs["poolclass"] = StaticPool
    return create_async_engine(dsn, **kwargs)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _compute_oldest_days(raw_val: Any) -> int | None:
    if raw_val is None:
        return None
    dt: datetime | None = None
    if isinstance(raw_val, datetime):
        dt = raw_val
    elif isinstance(raw_val, date):
        dt = datetime(raw_val.year, raw_val.month, raw_val.day, tzinfo=UTC)
    elif isinstance(raw_val, str) and raw_val.strip():
        candidate = raw_val.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return None
    if dt is None:
        return None
    normalized = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    delta = datetime.now(UTC) - normalized
    return max(0, delta.days)


async def _count_orphans(
    conn: AsyncConnection,
    table_name: str,
    fk_col: str,
    ref_table: str,
    ref_col: str,
    known_tables: set[str],
) -> int:
    if ref_table.lower() not in known_tables:
        return 0
    try:
        q_table = quote_ident(table_name)
        q_fk = quote_ident(fk_col)
        q_ref = quote_ident(ref_table)
        q_rc = quote_ident(ref_col)
        sql = (
            f"SELECT COUNT(*) FROM {q_table} t "
            f"LEFT JOIN {q_ref} r ON r.{q_rc} = t.{q_fk} "
            f"WHERE t.{q_fk} IS NOT NULL AND r.{q_rc} IS NULL"
        )
        res = await conn.execute(text(sql))
        return int(res.scalar_one() or 0)
    except Exception:
        return 0


async def _introspect_sqlite(conn: AsyncConnection) -> list[TableMeta]:
    table_rows = (
        await conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        )
    ).fetchall()
    table_names = [str(row[0]) for row in table_rows]
    known_lower = {name.lower() for name in table_names}
    results: list[TableMeta] = []

    for table_name in table_names:
        q_tbl = quote_ident(table_name)
        cols_raw = (await conn.execute(text(f"PRAGMA table_info({q_tbl})"))).fetchall()
        columns: list[ColumnMeta] = []
        primary_key: list[str] = []
        for col in cols_raw:
            col_name = str(col[1])
            col_type = str(col[2] or "TEXT")
            not_null = bool(col[3])
            is_pk = int(col[5] or 0) > 0
            if is_pk:
                primary_key.append(col_name)
            columns.append(
                ColumnMeta(
                    name=col_name,
                    data_type=col_type,
                    nullable=not not_null and not is_pk,
                    is_primary_key=is_pk,
                )
            )

        fks_raw = (await conn.execute(text(f"PRAGMA foreign_key_list({q_tbl})"))).fetchall()
        foreign_keys: list[ForeignKeyMeta] = []
        for fk in fks_raw:
            ref_table = str(fk[2])
            fk_col = str(fk[3])
            ref_col = str(fk[4] or "id")
            orphans = await _count_orphans(
                conn,
                table_name,
                fk_col,
                ref_table,
                ref_col,
                known_lower,
            )
            foreign_keys.append(
                ForeignKeyMeta(
                    column=fk_col,
                    ref_table=ref_table,
                    ref_column=ref_col,
                    orphan_count=orphans,
                )
            )

        idx_list_raw = (await conn.execute(text(f"PRAGMA index_list({q_tbl})"))).fetchall()
        indexes: list[IndexMeta] = []
        for idx_row in idx_list_raw:
            idx_name = str(idx_row[1])
            is_unique = bool(idx_row[2])
            idx_cols_raw = (
                await conn.execute(text(f"PRAGMA index_info({quote_ident(idx_name)})"))
            ).fetchall()
            idx_cols = [str(c[2]) for c in idx_cols_raw if c[2] is not None]
            if idx_cols:
                indexes.append(IndexMeta(name=idx_name, columns=idx_cols, unique=is_unique))

        row_count = int((await conn.execute(text(f"SELECT COUNT(*) FROM {q_tbl}"))).scalar_one())

        oldest_days: int | None = None
        for col_meta in columns:
            if (
                col_meta.name.lower() in _TIMESTAMP_HINTS
                or "timestamp" in col_meta.data_type.lower()
            ):
                min_val = (
                    await conn.execute(
                        text(f"SELECT MIN({quote_ident(col_meta.name)}) FROM {q_tbl}")
                    )
                ).scalar_one_or_none()
                oldest_days = _compute_oldest_days(min_val)
                if oldest_days is not None:
                    break

        results.append(
            TableMeta(
                name=table_name,
                columns=columns,
                primary_key=primary_key,
                foreign_keys=foreign_keys,
                indexes=indexes,
                row_count=row_count,
                oldest_record_days=oldest_days,
            )
        )
    return results


async def _introspect_postgres(conn: AsyncConnection) -> list[TableMeta]:
    table_rows = (
        await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
        )
    ).fetchall()
    table_names = [str(r[0]) for r in table_rows]
    known_lower = {name.lower() for name in table_names}

    col_rows = (
        await conn.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public' "
                "ORDER BY table_name, ordinal_position"
            )
        )
    ).fetchall()

    pk_rows = (
        await conn.execute(
            text(
                "SELECT tc.table_name, kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "AND tc.table_schema = kcu.table_schema "
                "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'PRIMARY KEY' "
                "ORDER BY tc.table_name, kcu.ordinal_position"
            )
        )
    ).fetchall()

    fk_rows = (
        await conn.execute(
            text(
                "SELECT tc.table_name, kcu.column_name, "
                "ccu.table_name AS ref_table, ccu.column_name AS ref_column "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "AND tc.table_schema = kcu.table_schema "
                "JOIN information_schema.constraint_column_usage ccu "
                "ON ccu.constraint_name = tc.constraint_name "
                "AND ccu.table_schema = tc.table_schema "
                "WHERE tc.table_schema = 'public' AND tc.constraint_type = 'FOREIGN KEY'"
            )
        )
    ).fetchall()

    stat_rows = (
        await conn.execute(
            text(
                "SELECT relname, n_live_tup, seq_scan, idx_scan "
                "FROM pg_stat_user_tables WHERE schemaname = 'public'"
            )
        )
    ).fetchall()
    stats_map = {
        str(r[0]): (int(r[1] or 0), int(r[2] or 0), int(r[3] or 0))
        for r in stat_rows
    }

    idx_rows = (
        await conn.execute(
            text(
                "SELECT i.tablename, i.indexname, i.indexdef, COALESCE(s.idx_scan, 0) "
                "FROM pg_indexes i "
                "LEFT JOIN pg_stat_user_indexes s "
                "ON s.schemaname = i.schemaname AND s.indexrelname = i.indexname "
                "WHERE i.schemaname = 'public'"
            )
        )
    ).fetchall()

    pks_by_table: dict[str, list[str]] = {}
    for tbl, col in pk_rows:
        pks_by_table.setdefault(str(tbl), []).append(str(col))

    cols_by_table: dict[str, list[ColumnMeta]] = {}
    for tbl, col, dtype, nullable in col_rows:
        tbl_s = str(tbl)
        col_s = str(col)
        is_pk = col_s in pks_by_table.get(tbl_s, [])
        cols_by_table.setdefault(tbl_s, []).append(
            ColumnMeta(
                name=col_s,
                data_type=str(dtype),
                nullable=str(nullable).upper() == "YES",
                is_primary_key=is_pk,
            )
        )

    fks_by_table: dict[str, list[ForeignKeyMeta]] = {}
    for tbl, col, ref_tbl, ref_col in fk_rows:
        orphans = await _count_orphans(
            conn,
            str(tbl),
            str(col),
            str(ref_tbl),
            str(ref_col),
            known_lower,
        )
        fks_by_table.setdefault(str(tbl), []).append(
            ForeignKeyMeta(
                column=str(col),
                ref_table=str(ref_tbl),
                ref_column=str(ref_col),
                orphan_count=orphans,
            )
        )

    idxs_by_table: dict[str, list[IndexMeta]] = {}
    for tbl, idx_name, idx_def, scans in idx_rows:
        def_str = str(idx_def)
        is_unique = "UNIQUE INDEX" in def_str.upper()
        cols: list[str] = []
        if "(" in def_str and ")" in def_str:
            inner = def_str[def_str.rfind("(") + 1 : def_str.rfind(")")]
            cols = [p.strip().split()[0].strip('"') for p in inner.split(",") if p.strip()]
        idxs_by_table.setdefault(str(tbl), []).append(
            IndexMeta(name=str(idx_name), columns=cols, unique=is_unique, scans=int(scans))
        )

    results: list[TableMeta] = []
    for table_name in table_names:
        table_cols = cols_by_table.get(table_name, [])
        row_count, seq_scans, idx_scans = stats_map.get(table_name, (0, 0, 0))
        if row_count == 0:
            count_res = await conn.execute(
                text(f"SELECT COUNT(*) FROM {quote_ident(table_name)}")
            )
            row_count = int(count_res.scalar_one())
        oldest_days: int | None = None
        for col_meta in table_cols:
            if (
                col_meta.name.lower() in _TIMESTAMP_HINTS
                or "timestamp" in col_meta.data_type.lower()
            ):
                min_val = (
                    await conn.execute(
                        text(
                            f"SELECT MIN({quote_ident(col_meta.name)}) "
                            f"FROM {quote_ident(table_name)}"
                        )
                    )
                ).scalar_one_or_none()
                oldest_days = _compute_oldest_days(min_val)
                if oldest_days is not None:
                    break
        results.append(
            TableMeta(
                name=table_name,
                columns=table_cols,
                primary_key=pks_by_table.get(table_name, []),
                foreign_keys=fks_by_table.get(table_name, []),
                indexes=idxs_by_table.get(table_name, []),
                row_count=row_count,
                seq_scans=seq_scans,
                idx_scans=idx_scans,
                oldest_record_days=oldest_days,
            )
        )
    return results


async def test_connection(dsn: str) -> tuple[bool, str, float, int, str | None]:
    """Verify connectivity to target database and count user tables."""
    engine = create_connector_engine(dsn)
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            dialect = conn.dialect.name
            if dialect == "sqlite":
                rows = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM sqlite_master "
                            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )
                    )
                ).scalar_one()
            else:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.tables "
                            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                        )
                    )
                ).scalar_one()
            latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
            return True, dialect, latency_ms, int(rows or 0), None
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
        return False, "unknown", latency_ms, 0, str(exc)
    finally:
        await engine.dispose()


async def introspect_tables(dsn: str) -> list[TableMeta]:
    """Introspect live SQLite or PostgreSQL tables, columns, keys, indexes, and stats."""
    engine = create_connector_engine(dsn)
    try:
        async with engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                return await _introspect_sqlite(conn)
            return await _introspect_postgres(conn)
    finally:
        await engine.dispose()


async def sample_table_rows(
    dsn: str,
    table_name: str,
    *,
    limit: int = 50,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Sample bounded rows from a validated live table."""
    safe_table = validate_ident(table_name)
    bounded_limit = max(1, min(limit, 500))
    tables = await introspect_tables(dsn)
    table_meta = next((t for t in tables if t.name == safe_table), None)
    if table_meta is None:
        raise ValueError(f"Table '{safe_table}' not found in target database.")

    engine = create_connector_engine(dsn)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT * FROM {quote_ident(safe_table)} LIMIT :limit"),
                {"limit": bounded_limit},
            )
            keys = list(result.keys())
            rows = [
                {col: _json_safe(val) for col, val in zip(keys, row, strict=False)}
                for row in result.fetchall()
            ]
            return keys, rows
    finally:
        await engine.dispose()
