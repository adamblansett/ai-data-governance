import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command


def test_alembic_upgrade_and_downgrade(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "alembic_verify.db"

    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {
            "alembic_version",
            "pii_vault_entries",
            "governance_proposals",
            "audit_events",
            "data_connectors",
            "background_jobs",
        }.issubset(tables)
    finally:
        conn.close()

    command.downgrade(cfg, "base")

    conn = sqlite3.connect(str(db_path))
    try:
        tables_after = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "governance_proposals" not in tables_after
        assert "data_connectors" not in tables_after
    finally:
        conn.close()

    command.upgrade(cfg, "head")
