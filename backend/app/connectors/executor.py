from typing import Any

from sqlalchemy import text

from app.connectors.inspector import (
    create_connector_engine,
    introspect_tables,
    quote_ident,
    validate_ident,
)

_ALLOWED_DDL_PREFIXES = (
    "CREATE INDEX",
    "CREATE UNIQUE INDEX",
    "DROP INDEX",
    "ALTER TABLE",
    "COMMENT ON",
    "ANALYZE",
    "CREATE TABLE IF NOT EXISTS",
    "DELETE FROM",
)


def _split_sql_statements(raw_sql: str) -> list[str]:
    statements: list[str] = []
    for chunk in raw_sql.split(";"):
        lines = [
            line
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def _validate_ddl_statement(stmt: str) -> str:
    upper = " ".join(stmt.upper().split())
    if not any(upper.startswith(prefix) for prefix in _ALLOWED_DDL_PREFIXES):
        raise ValueError(f"Disallowed remediation SQL statement: {stmt[:80]}")
    return stmt


async def apply_proposal_to_connector(
    dsn: str,
    *,
    action_type: str,
    payload: dict[str, Any],
    before_snapshot: Any,
) -> tuple[Any, dict[str, Any]]:
    """Execute an approved HITL proposal transactionally on a live target database."""
    tables = await introspect_tables(dsn)
    tables_by_name = {t.name: t for t in tables}
    engine = create_connector_engine(dsn)

    try:
        async with engine.begin() as conn:
            if action_type == "bulk_normalize":
                target_table = validate_ident(str(payload["target_table"]))
                id_field = validate_ident(str(payload.get("id_field", "id")))
                table_meta = tables_by_name.get(target_table)
                if table_meta is None:
                    raise ValueError(f"Target table '{target_table}' not found.")
                valid_cols = {c.name for c in table_meta.columns}
                if id_field not in valid_cols:
                    raise ValueError(f"Primary key field '{id_field}' not in '{target_table}'.")

                normalized_records: list[dict[str, Any]] = list(
                    payload.get("normalized_records") or []
                )
                captured_before: list[dict[str, Any]] = []
                updated_rows = 0

                q_tbl = quote_ident(target_table)
                q_pk = quote_ident(id_field)
                for rec in normalized_records:
                    if id_field not in rec or rec[id_field] is None:
                        continue
                    pk_val = rec[id_field]
                    cur_res = await conn.execute(
                        text(f"SELECT * FROM {q_tbl} WHERE {q_pk} = :pk"),
                        {"pk": pk_val},
                    )
                    row = cur_res.fetchone()
                    if row is None:
                        continue
                    cols = list(cur_res.keys())
                    orig_dict = dict(zip(cols, row, strict=False))
                    captured_before.append(orig_dict)

                    set_clauses: list[str] = []
                    params: dict[str, Any] = {"pk": pk_val}
                    for idx, (col, new_val) in enumerate(rec.items()):
                        if col == id_field or col not in valid_cols:
                            continue
                        if orig_dict.get(col) != new_val:
                            param_name = f"v_{idx}"
                            set_clauses.append(f"{quote_ident(col)} = :{param_name}")
                            params[param_name] = new_val
                    if set_clauses:
                        await conn.execute(
                            text(
                                f"UPDATE {q_tbl} SET {', '.join(set_clauses)} WHERE {q_pk} = :pk"
                            ),
                            params,
                        )
                        updated_rows += 1

                return captured_before or before_snapshot, {
                    "executed_on_connector": True,
                    "target_table": target_table,
                    "updated_rows": updated_rows,
                    "records": normalized_records,
                }

            if action_type == "record_merge":
                target_table = validate_ident(str(payload["target_table"]))
                id_field = validate_ident(str(payload.get("id_field", "id")))
                table_meta = tables_by_name.get(target_table)
                if table_meta is None:
                    raise ValueError(f"Target table '{target_table}' not found.")
                valid_cols = {c.name for c in table_meta.columns}

                golden: dict[str, Any] = dict(payload.get("golden_record") or {})
                record_ids: list[Any] = list(payload.get("record_ids") or [])
                keeper_id = golden.get(id_field)
                if keeper_id is None or not record_ids:
                    raise ValueError("Merge payload requires golden_record ID and record_ids.")

                q_tbl = quote_ident(target_table)
                q_pk = quote_ident(id_field)

                captured_before = []
                for rid in record_ids:
                    res = await conn.execute(
                        text(f"SELECT * FROM {q_tbl} WHERE {q_pk} = :pk"),
                        {"pk": rid},
                    )
                    row = res.fetchone()
                    if row is not None:
                        captured_before.append(dict(zip(res.keys(), row, strict=False)))

                set_clauses = []
                params = {"pk": keeper_id}
                for idx, (col, val) in enumerate(golden.items()):
                    if col == id_field or col not in valid_cols:
                        continue
                    param_name = f"g_{idx}"
                    set_clauses.append(f"{quote_ident(col)} = :{param_name}")
                    params[param_name] = val
                if set_clauses:
                    await conn.execute(
                        text(f"UPDATE {q_tbl} SET {', '.join(set_clauses)} WHERE {q_pk} = :pk"),
                        params,
                    )

                deleted_ids: list[Any] = []
                for rid in record_ids:
                    if str(rid) == str(keeper_id):
                        continue
                    await conn.execute(
                        text(f"DELETE FROM {q_tbl} WHERE {q_pk} = :pk"),
                        {"pk": rid},
                    )
                    deleted_ids.append(rid)

                return captured_before or before_snapshot, {
                    "executed_on_connector": True,
                    "target_table": target_table,
                    "keeper_id": keeper_id,
                    "deleted_ids": deleted_ids,
                    "golden_record": golden,
                }

            if action_type == "schema_remediation":
                executed: list[str] = []
                for item in payload.get("statements") or []:
                    raw_sql = item.get("sql", "") if isinstance(item, dict) else str(item)
                    for stmt in _split_sql_statements(raw_sql):
                        validated = _validate_ddl_statement(stmt)
                        # SQLite does not support CONCURRENTLY keyword on INDEX DDL
                        if conn.dialect.name == "sqlite":
                            validated = validated.replace(" CONCURRENTLY ", " ")
                        await conn.execute(text(validated))
                        executed.append(validated)
                return before_snapshot, {
                    "executed_on_connector": True,
                    "executed_statements": len(executed),
                    "statements": executed,
                }

            return before_snapshot, {"executed_on_connector": False}
    finally:
        await engine.dispose()


async def rollback_proposal_on_connector(
    dsn: str,
    *,
    action_type: str,
    payload: dict[str, Any],
    before_snapshot: Any,
) -> dict[str, Any]:
    """Roll back an applied HITL proposal on a live target database."""
    if action_type == "schema_remediation":
        return {
            "rolled_back_on_connector": False,
            "note": "DDL remediations require explicit compensating DDL.",
        }

    if not isinstance(before_snapshot, list) or not before_snapshot:
        return {"rolled_back_on_connector": False, "note": "No live row snapshot captured."}

    target_table = validate_ident(str(payload["target_table"]))
    id_field = validate_ident(str(payload.get("id_field", "id")))
    tables = await introspect_tables(dsn)
    table_meta = next((t for t in tables if t.name == target_table), None)
    if table_meta is None:
        raise ValueError(f"Target table '{target_table}' not found for rollback.")
    valid_cols = {c.name for c in table_meta.columns}

    q_tbl = quote_ident(target_table)
    q_pk = quote_ident(id_field)

    engine = create_connector_engine(dsn)
    try:
        async with engine.begin() as conn:
            restored = 0
            for orig_row in before_snapshot:
                if not isinstance(orig_row, dict) or id_field not in orig_row:
                    continue
                pk_val = orig_row[id_field]
                exists = (
                    await conn.execute(
                        text(f"SELECT 1 FROM {q_tbl} WHERE {q_pk} = :pk"),
                        {"pk": pk_val},
                    )
                ).fetchone()

                filtered_row = {k: v for k, v in orig_row.items() if k in valid_cols}
                if exists is not None:
                    set_clauses = [
                        f"{quote_ident(col)} = :u_{idx}"
                        for idx, col in enumerate(filtered_row)
                        if col != id_field
                    ]
                    params: dict[str, Any] = {"pk": pk_val}
                    for idx, col in enumerate(filtered_row):
                        if col != id_field:
                            params[f"u_{idx}"] = filtered_row[col]
                    if set_clauses:
                        await conn.execute(
                            text(
                                f"UPDATE {q_tbl} SET {', '.join(set_clauses)} WHERE {q_pk} = :pk"
                            ),
                            params,
                        )
                else:
                    cols_sql = ", ".join(quote_ident(col) for col in filtered_row)
                    vals_sql = ", ".join(f":i_{idx}" for idx in range(len(filtered_row)))
                    ins_params = {
                        f"i_{idx}": val for idx, val in enumerate(filtered_row.values())
                    }
                    await conn.execute(
                        text(f"INSERT INTO {q_tbl} ({cols_sql}) VALUES ({vals_sql})"),
                        ins_params,
                    )
                restored += 1

        return {
            "rolled_back_on_connector": True,
            "target_table": target_table,
            "restored_rows": restored,
        }
    finally:
        await engine.dispose()
