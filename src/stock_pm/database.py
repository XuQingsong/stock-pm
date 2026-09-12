from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings, redact_database_url
from .errors import DatabaseError
from .migrate import apply_migrations, verify_migrations
from .persist import PersistMixin
from .queries import QueryMixin

__all__ = ["Database", "DatabaseError"]


class Database(QueryMixin, PersistMixin):
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.pool = self._open_pool(self.settings)
        self._watchlist_cache: tuple[float, list[dict]] = (0.0, [])

    @staticmethod
    def _open_pool(settings: Settings) -> ConnectionPool:
        return ConnectionPool(
            conninfo=settings.database_url,
            min_size=0,
            max_size=settings.database_pool_size,
            open=True,
            kwargs={"row_factory": dict_row, "connect_timeout": 2},
        )

    def close(self) -> None:
        self.pool.close()

    def reconnect(self) -> bool:
        try:
            self.pool.close()
        except Exception:
            pass
        self.settings = Settings()
        self.pool = self._open_pool(self.settings)
        return self.ping()

    def ping(self) -> bool:
        """Health probe uses a short standalone connect so a wedged pool cannot hang /health."""
        try:
            with psycopg.connect(
                self.settings.database_url,
                connect_timeout=2,
                row_factory=dict_row,
            ) as conn:
                return conn.execute("SELECT 1").fetchone() is not None
        except Exception:
            return False

    def monitor_status(self) -> dict[str, Any]:
        reachable = self.ping()
        return {
            "status": "ok" if reachable else "error",
            "reachable": reachable,
            "database": "connected" if reachable else "unavailable",
            "reason_code": None if reachable else "query_error",
            "note": None if reachable else "PostgreSQL unreachable; live overlay does not hide this",
            "dsn": redact_database_url(self.settings.database_url),
        }

    def initialize(self) -> None:
        from .config import DEFAULT_WATCHLIST

        try:
            with self.pool.connection() as conn:
                apply_migrations(conn)
                verify = verify_migrations(conn)
                if verify["status"] != "ok":
                    raise DatabaseError(f"migration verify failed: {verify}")
                for item in DEFAULT_WATCHLIST.values():
                    conn.execute(
                        """
                        INSERT INTO watchlist
                            (symbol, name, primary_exchange, asset_class,
                             sector, themes, rate_sensitivity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol) DO NOTHING
                        """,
                        (
                            item.symbol,
                            item.name,
                            item.primary_exchange,
                            item.asset_class,
                            item.sector,
                            list(item.themes),
                            item.rate_sensitivity,
                        ),
                    )
        except DatabaseError:
            raise
        except Exception as exc:
            raise DatabaseError(f"PostgreSQL initialization failed: {exc}") from exc

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict]:
        try:
            with self.pool.connection() as conn:
                return list(conn.execute(query, params).fetchall())
        except Exception as exc:
            raise DatabaseError(f"PostgreSQL query failed: {exc}") from exc
