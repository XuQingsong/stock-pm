from __future__ import annotations

from importlib.resources import files
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Settings
from .errors import DatabaseError
from .persist import PersistMixin
from .queries import QueryMixin

__all__ = ["Database", "DatabaseError"]


class Database(QueryMixin, PersistMixin):
    def __init__(self, settings: Settings | None = None) -> None:
        config = settings or Settings()
        self.pool = ConnectionPool(
            conninfo=config.database_url,
            min_size=0,
            max_size=config.database_pool_size,
            open=True,
            kwargs={"row_factory": dict_row},
        )
        self._watchlist_cache: tuple[float, list[dict]] = (0.0, [])

    def close(self) -> None:
        self.pool.close()

    def ping(self) -> bool:
        try:
            with self.pool.connection(timeout=2) as conn:
                return conn.execute("SELECT 1").fetchone() is not None
        except Exception:
            return False

    def initialize(self) -> None:
        from .config import DEFAULT_WATCHLIST

        schema_path = files("stock_pm").joinpath("sql/schema.sql")
        try:
            with self.pool.connection() as conn:
                conn.execute(schema_path.read_text(encoding="utf-8"))
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
        except Exception as exc:
            raise DatabaseError(f"PostgreSQL initialization failed: {exc}") from exc

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict]:
        try:
            with self.pool.connection() as conn:
                return list(conn.execute(query, params).fetchall())
        except Exception as exc:
            raise DatabaseError(f"PostgreSQL query failed: {exc}") from exc
