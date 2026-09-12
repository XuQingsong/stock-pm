"""Apply numbered SQL migrations and record them in schema_migrations.

0001 is the current schema.sql snapshot. Later files live in sql/migrations/.
SQL is written to be re-runnable (IF NOT EXISTS). Real credentials never enter
migration files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings, redact_database_url
from .errors import DatabaseError


MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    filename TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    filename: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def _sql_root() -> Path:
    return Path(str(files("stock_pm").joinpath("sql")))


def discover_migrations() -> list[Migration]:
    root = _sql_root()
    schema = root / "schema.sql"
    if not schema.is_file():
        raise DatabaseError("sql/schema.sql is missing")
    items = [
        Migration(version="0001_initial", filename="schema.sql", sql=schema.read_text(encoding="utf-8")),
    ]
    extra = root / "migrations"
    if extra.is_dir():
        for path in sorted(extra.glob("*.sql")):
            version = path.stem
            if version.startswith("0001"):
                continue
            items.append(
                Migration(version=version, filename=f"migrations/{path.name}", sql=path.read_text(encoding="utf-8"))
            )
    items.sort(key=lambda item: item.version)
    return items


def _connect(settings: Settings | None = None) -> ConnectionPool:
    config = settings or Settings()
    return ConnectionPool(
        conninfo=config.database_url,
        min_size=0,
        max_size=1,
        open=True,
        kwargs={"row_factory": dict_row, "connect_timeout": 2},
    )


def apply_migrations(conn, migrations: list[Migration] | None = None) -> dict[str, Any]:
    pending = migrations or discover_migrations()
    conn.execute(MIGRATIONS_TABLE_SQL)
    applied = {
        row["version"]: row
        for row in conn.execute(
            "SELECT version, checksum, filename, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    }
    report: dict[str, Any] = {"applied": [], "skipped": [], "updated": []}
    for item in pending:
        existing = applied.get(item.version)
        if existing and existing["checksum"] == item.checksum:
            report["skipped"].append(item.version)
            continue
        conn.execute(item.sql)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, checksum, filename)
            VALUES (%s, %s, %s)
            ON CONFLICT (version) DO UPDATE SET
                checksum = EXCLUDED.checksum,
                filename = EXCLUDED.filename,
                applied_at = CURRENT_TIMESTAMP
            """,
            (item.version, item.checksum, item.filename),
        )
        if existing:
            report["updated"].append(item.version)
        else:
            report["applied"].append(item.version)
    return report


def verify_migrations(conn, migrations: list[Migration] | None = None) -> dict[str, Any]:
    pending = migrations or discover_migrations()
    rows = list(
        conn.execute(
            "SELECT version, checksum, filename FROM schema_migrations ORDER BY version"
        ).fetchall()
    )
    expected = {item.version: item.checksum for item in pending}
    present = {row["version"]: row["checksum"] for row in rows}
    missing = [version for version in expected if version not in present]
    mismatched = [
        version for version, checksum in expected.items()
        if version in present and present[version] != checksum
    ]
    extra = [version for version in present if version not in expected]
    status = "ok" if not missing and not mismatched else "error"
    return {
        "status": status,
        "expected": list(expected),
        "present": list(present),
        "missing": missing,
        "mismatched": mismatched,
        "extra": extra,
    }


def migrate(settings: Settings | None = None) -> dict[str, Any]:
    config = settings or Settings()
    pool = _connect(config)
    try:
        with pool.connection() as conn:
            applied = apply_migrations(conn)
            verified = verify_migrations(conn)
        return {
            "status": "ok" if verified["status"] == "ok" else "error",
            "database": redact_database_url(config.database_url),
            "apply": applied,
            "verify": verified,
        }
    except Exception as exc:
        raise DatabaseError(f"PostgreSQL migration failed: {exc}") from exc
    finally:
        pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply and verify PostgreSQL migrations")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.verify_only:
        pool = _connect(settings)
        try:
            with pool.connection() as conn:
                report = {
                    "status": "ok",
                    "database": redact_database_url(settings.database_url),
                    "verify": verify_migrations(conn),
                }
                report["status"] = report["verify"]["status"]
        finally:
            pool.close()
    else:
        report = migrate(settings)
    print(json.dumps(report, ensure_ascii=False, default=str))
    if report.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
