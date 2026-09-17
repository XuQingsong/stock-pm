"""Brain persistence. Postgres when a Database is provided; otherwise in-memory."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from stock_pm.errors import DatabaseError
from stock_pm.research.ids import new_id


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _row(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {str(key): _plain(value) for key, value in payload.items()}


def _rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_row(item) or {} for item in items]


def _jsonb(value: Any) -> Jsonb:
    return Jsonb(_plain(value) if value is not None else {})


def _copy(row: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(row)


class BrainStore:
    def __init__(self, database: Any | None = None) -> None:
        self.database = database
        self.runs: dict[str, dict[str, Any]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.links: list[dict[str, Any]] = []
        self.questions: dict[str, dict[str, Any]] = {}
        self.news: dict[str, dict[str, Any]] = {}

    def _pg(self) -> bool:
        return self.database is not None

    def _execute(self, query: str, params: dict[str, Any] | tuple | None = None) -> list[dict[str, Any]]:
        try:
            with self.database.pool.connection() as conn:
                result = conn.execute(query, params or {})
                if result.description is None:
                    return []
                return _rows(list(result.fetchall()))
        except Exception as exc:
            raise DatabaseError(f"brain store failed: {exc}") from exc

    def _one(self, query: str, params: dict[str, Any] | tuple | None = None) -> dict[str, Any] | None:
        rows = self._execute(query, params)
        return rows[0] if rows else None

    def insert_run(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "run_id": row.get("run_id") or new_id("brun"),
            "ticker": str(row["ticker"]).upper(),
            "snapshot_id": row.get("snapshot_id"),
            "status": row.get("status") or "running",
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version") or "brain-phase1-v1",
            "llm_calls": list(row.get("llm_calls") or []),
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "latency_ms": row.get("latency_ms"),
            "news_searched": int(row.get("news_searched") or 0),
            "sources_fetched": int(row.get("sources_fetched") or 0),
            "evidence_created": int(row.get("evidence_created") or 0),
            "candidate_claim_count": int(row.get("candidate_claim_count") or 0),
            "core_claim_count": int(row.get("core_claim_count") or 0),
            "claim_versions_changed": int(row.get("claim_versions_changed") or 0),
            "errors": list(row.get("errors") or []),
            "warnings": list(row.get("warnings") or []),
            "fallbacks": list(row.get("fallbacks") or []),
            "quality": dict(row.get("quality") or {}),
            "company_understanding": dict(row.get("company_understanding") or {}),
            "pm_synthesis": dict(row.get("pm_synthesis") or {}),
            "header": dict(row.get("header") or {}),
            "audit": dict(row.get("audit") or {}),
            "created_at": row.get("created_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        if not self._pg():
            self.runs[stored["run_id"]] = stored
            return _copy(stored)
        payload = {
            **stored,
            "llm_calls": _jsonb(stored["llm_calls"]),
            "errors": _jsonb(stored["errors"]),
            "warnings": _jsonb(stored["warnings"]),
            "fallbacks": _jsonb(stored["fallbacks"]),
            "quality": _jsonb(stored["quality"]),
            "company_understanding": _jsonb(stored["company_understanding"]),
            "pm_synthesis": _jsonb(stored["pm_synthesis"]),
            "header": _jsonb(stored["header"]),
            "audit": _jsonb(stored["audit"]),
        }
        out = self._one(
            """
            INSERT INTO brain_runs (
                run_id, ticker, snapshot_id, status, model, prompt_version, llm_calls,
                input_tokens, output_tokens, latency_ms, news_searched, sources_fetched,
                evidence_created, candidate_claim_count, core_claim_count, claim_versions_changed,
                errors, warnings, fallbacks, quality, company_understanding, pm_synthesis,
                header, audit, created_at, completed_at
            ) VALUES (
                %(run_id)s, %(ticker)s, %(snapshot_id)s, %(status)s, %(model)s, %(prompt_version)s,
                %(llm_calls)s, %(input_tokens)s, %(output_tokens)s, %(latency_ms)s, %(news_searched)s,
                %(sources_fetched)s, %(evidence_created)s, %(candidate_claim_count)s,
                %(core_claim_count)s, %(claim_versions_changed)s, %(errors)s, %(warnings)s,
                %(fallbacks)s, %(quality)s, %(company_understanding)s, %(pm_synthesis)s,
                %(header)s, %(audit)s, %(created_at)s, %(completed_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def complete_run(self, run_id: str, row: dict[str, Any]) -> dict[str, Any]:
        if not self._pg():
            current = dict(self.runs.get(run_id) or {})
            current.update(row)
            current["completed_at"] = row.get("completed_at") or _now()
            self.runs[run_id] = current
            return _copy(current)
        payload = {
            "run_id": run_id,
            "status": row.get("status") or "success",
            "model": row.get("model"),
            "llm_calls": _jsonb(row.get("llm_calls") or []),
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "latency_ms": row.get("latency_ms"),
            "news_searched": int(row.get("news_searched") or 0),
            "sources_fetched": int(row.get("sources_fetched") or 0),
            "evidence_created": int(row.get("evidence_created") or 0),
            "candidate_claim_count": int(row.get("candidate_claim_count") or 0),
            "core_claim_count": int(row.get("core_claim_count") or 0),
            "claim_versions_changed": int(row.get("claim_versions_changed") or 0),
            "errors": _jsonb(row.get("errors") or []),
            "warnings": _jsonb(row.get("warnings") or []),
            "fallbacks": _jsonb(row.get("fallbacks") or []),
            "quality": _jsonb(row.get("quality") or {}),
            "company_understanding": _jsonb(row.get("company_understanding") or {}),
            "pm_synthesis": _jsonb(row.get("pm_synthesis") or {}),
            "header": _jsonb(row.get("header") or {}),
            "audit": _jsonb(row.get("audit") or {}),
            "snapshot_id": row.get("snapshot_id"),
            "completed_at": row.get("completed_at") or _now(),
        }
        out = self._one(
            """
            UPDATE brain_runs SET
                status = %(status)s,
                model = %(model)s,
                llm_calls = %(llm_calls)s,
                input_tokens = %(input_tokens)s,
                output_tokens = %(output_tokens)s,
                latency_ms = %(latency_ms)s,
                news_searched = %(news_searched)s,
                sources_fetched = %(sources_fetched)s,
                evidence_created = %(evidence_created)s,
                candidate_claim_count = %(candidate_claim_count)s,
                core_claim_count = %(core_claim_count)s,
                claim_versions_changed = %(claim_versions_changed)s,
                errors = %(errors)s,
                warnings = %(warnings)s,
                fallbacks = %(fallbacks)s,
                quality = %(quality)s,
                company_understanding = %(company_understanding)s,
                pm_synthesis = %(pm_synthesis)s,
                header = %(header)s,
                audit = %(audit)s,
                snapshot_id = %(snapshot_id)s,
                completed_at = %(completed_at)s
            WHERE run_id = %(run_id)s
            RETURNING *
            """,
            payload,
        )
        return out or {}

    def latest_run(self, ticker: str) -> dict[str, Any] | None:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.runs.values() if row.get("ticker") == symbol]
            rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return _copy(rows[0]) if rows else None
        return self._one(
            "SELECT * FROM brain_runs WHERE ticker = %(ticker)s ORDER BY created_at DESC LIMIT 1",
            {"ticker": symbol},
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not self._pg():
            row = self.runs.get(run_id)
            return _copy(row) if row else None
        return self._one("SELECT * FROM brain_runs WHERE run_id = %(run_id)s", {"run_id": run_id})

    def insert_state(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "state_id": row.get("state_id") or new_id("bst"),
            "ticker": (str(row.get("ticker") or "").upper() or None),
            "state_type": row.get("state_type") or "company",
            "name": row.get("name") or "",
            "statement": row.get("statement") or "",
            "direction": row.get("direction"),
            "confidence": row.get("confidence"),
            "effective_at": row.get("effective_at") or _now(),
            "expires_at": row.get("expires_at"),
            "evidence_ids": list(row.get("evidence_ids") or []),
            "source": row.get("source"),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            self.states[stored["state_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_states (
                state_id, ticker, state_type, name, statement, direction, confidence,
                effective_at, expires_at, evidence_ids, source, run_id, created_at, updated_at
            ) VALUES (
                %(state_id)s, %(ticker)s, %(state_type)s, %(name)s, %(statement)s, %(direction)s,
                %(confidence)s, %(effective_at)s, %(expires_at)s, %(evidence_ids)s, %(source)s,
                %(run_id)s, %(created_at)s, %(updated_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_states(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.states.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        if run_id:
            return self._execute(
                "SELECT * FROM brain_states WHERE ticker = %(ticker)s AND run_id = %(run_id)s ORDER BY updated_at DESC",
                {"ticker": symbol, "run_id": run_id},
            )
        return self._execute(
            "SELECT * FROM brain_states WHERE ticker = %(ticker)s ORDER BY updated_at DESC",
            {"ticker": symbol},
        )

    def insert_claim(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "claim_id": row.get("claim_id") or new_id("bclm"),
            "ticker": str(row["ticker"]).upper(),
            "title": row.get("title") or "",
            "statement": row.get("statement") or "",
            "claim_type": row.get("claim_type") or "operating",
            "status": row.get("status") or "emerging",
            "importance": row.get("importance") or "medium",
            "confidence": row.get("confidence") or "low",
            "time_horizon": row.get("time_horizon"),
            "why_it_matters": row.get("why_it_matters") or "",
            "financial_driver": row.get("financial_driver"),
            "is_core": bool(row.get("is_core")),
            "current_version_id": row.get("current_version_id"),
            "reasoning": dict(row.get("reasoning") or {}),
            "run_id": row.get("run_id"),
            "snapshot_id": row.get("snapshot_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            self.claims[stored["claim_id"]] = stored
            return _copy(stored)
        payload = {**stored, "reasoning": _jsonb(stored["reasoning"])}
        out = self._one(
            """
            INSERT INTO brain_claims (
                claim_id, ticker, title, statement, claim_type, status, importance, confidence,
                time_horizon, why_it_matters, financial_driver, is_core, current_version_id,
                reasoning, run_id, snapshot_id, created_at, updated_at
            ) VALUES (
                %(claim_id)s, %(ticker)s, %(title)s, %(statement)s, %(claim_type)s, %(status)s,
                %(importance)s, %(confidence)s, %(time_horizon)s, %(why_it_matters)s,
                %(financial_driver)s, %(is_core)s, %(current_version_id)s, %(reasoning)s,
                %(run_id)s, %(snapshot_id)s, %(created_at)s, %(updated_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def update_claim_pointer(self, claim_id: str, row: dict[str, Any]) -> dict[str, Any]:
        """Point the claim at a new version. Historical statements stay on versions."""
        if not self._pg():
            current = dict(self.claims.get(claim_id) or {})
            for key in (
                "statement",
                "status",
                "confidence",
                "current_version_id",
                "reasoning",
                "is_core",
                "run_id",
                "snapshot_id",
            ):
                if key in row:
                    current[key] = row[key]
            current["updated_at"] = _now()
            self.claims[claim_id] = current
            return _copy(current)
        payload = {
            "claim_id": claim_id,
            "statement": row.get("statement"),
            "status": row.get("status"),
            "confidence": row.get("confidence"),
            "current_version_id": row.get("current_version_id"),
            "reasoning": _jsonb(row.get("reasoning") or {}),
            "is_core": row.get("is_core"),
            "run_id": row.get("run_id"),
            "snapshot_id": row.get("snapshot_id"),
            "updated_at": _now(),
        }
        out = self._one(
            """
            UPDATE brain_claims SET
                statement = COALESCE(%(statement)s, statement),
                status = COALESCE(%(status)s, status),
                confidence = COALESCE(%(confidence)s, confidence),
                current_version_id = COALESCE(%(current_version_id)s, current_version_id),
                reasoning = CASE WHEN %(reasoning)s = '{}'::jsonb THEN reasoning ELSE %(reasoning)s END,
                is_core = COALESCE(%(is_core)s, is_core),
                run_id = COALESCE(%(run_id)s, run_id),
                snapshot_id = COALESCE(%(snapshot_id)s, snapshot_id),
                updated_at = %(updated_at)s
            WHERE claim_id = %(claim_id)s
            RETURNING *
            """,
            payload,
        )
        return out or {}

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        if not self._pg():
            row = self.claims.get(claim_id)
            return _copy(row) if row else None
        return self._one("SELECT * FROM brain_claims WHERE claim_id = %(claim_id)s", {"claim_id": claim_id})

    def list_claims(self, ticker: str, *, run_id: str | None = None, core_only: bool = False) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.claims.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            if core_only:
                rows = [row for row in rows if row.get("is_core")]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_claims WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if run_id:
            query += " AND run_id = %(run_id)s"
            params["run_id"] = run_id
        if core_only:
            query += " AND is_core = TRUE"
        query += " ORDER BY is_core DESC, updated_at DESC"
        return self._execute(query, params)

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "claim_version_id": row.get("claim_version_id") or new_id("bclv"),
            "claim_id": row["claim_id"],
            "version": int(row.get("version") or 1),
            "statement": row.get("statement") or "",
            "status": row.get("status") or "emerging",
            "confidence": row.get("confidence") or "low",
            "reason_for_change": row.get("reason_for_change") or "",
            "added_evidence_ids": list(row.get("added_evidence_ids") or []),
            "removed_evidence_ids": list(row.get("removed_evidence_ids") or []),
            "counter_evidence_ids": list(row.get("counter_evidence_ids") or []),
            "snapshot_id": row.get("snapshot_id"),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.versions[stored["claim_version_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_claim_versions (
                claim_version_id, claim_id, version, statement, status, confidence,
                reason_for_change, added_evidence_ids, removed_evidence_ids, counter_evidence_ids,
                snapshot_id, run_id, created_at
            ) VALUES (
                %(claim_version_id)s, %(claim_id)s, %(version)s, %(statement)s, %(status)s,
                %(confidence)s, %(reason_for_change)s, %(added_evidence_ids)s, %(removed_evidence_ids)s,
                %(counter_evidence_ids)s, %(snapshot_id)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_versions(self, claim_id: str) -> list[dict[str, Any]]:
        if not self._pg():
            rows = [row for row in self.versions.values() if row.get("claim_id") == claim_id]
            rows.sort(key=lambda item: int(item.get("version") or 0))
            return [_copy(row) for row in rows]
        return self._execute(
            "SELECT * FROM brain_claim_versions WHERE claim_id = %(claim_id)s ORDER BY version",
            {"claim_id": claim_id},
        )

    def insert_link(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "link_id": row.get("link_id") or new_id("bcel"),
            "claim_id": row["claim_id"],
            "evidence_id": row["evidence_id"],
            "direction": row.get("direction") or "support",
            "strength": row.get("strength") or "medium",
            "relevance": row.get("relevance") or "direct",
            "reason": row.get("reason") or "",
            "proves": row.get("proves") or "",
            "does_not_prove": row.get("does_not_prove") or "",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.links.append(stored)
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_claim_evidence_links (
                link_id, claim_id, evidence_id, direction, strength, relevance,
                reason, proves, does_not_prove, run_id, created_at
            ) VALUES (
                %(link_id)s, %(claim_id)s, %(evidence_id)s, %(direction)s, %(strength)s,
                %(relevance)s, %(reason)s, %(proves)s, %(does_not_prove)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_links(self, *, claim_id: str | None = None, evidence_id: str | None = None) -> list[dict[str, Any]]:
        if not self._pg():
            rows = list(self.links)
            if claim_id:
                rows = [row for row in rows if row.get("claim_id") == claim_id]
            if evidence_id:
                rows = [row for row in rows if row.get("evidence_id") == evidence_id]
            return [_copy(row) for row in rows]
        if claim_id:
            return self._execute(
                "SELECT * FROM brain_claim_evidence_links WHERE claim_id = %(claim_id)s",
                {"claim_id": claim_id},
            )
        if evidence_id:
            return self._execute(
                "SELECT * FROM brain_claim_evidence_links WHERE evidence_id = %(evidence_id)s",
                {"evidence_id": evidence_id},
            )
        return []

    def insert_question(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "question_id": row.get("question_id") or new_id("brq"),
            "ticker": str(row["ticker"]).upper(),
            "related_claim_id": row.get("related_claim_id"),
            "question": row.get("question") or "",
            "why_it_matters": row.get("why_it_matters") or "",
            "priority": row.get("priority") or "medium",
            "status": row.get("status") or "open",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.questions[stored["question_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_research_questions (
                question_id, ticker, related_claim_id, question, why_it_matters,
                priority, status, run_id, created_at
            ) VALUES (
                %(question_id)s, %(ticker)s, %(related_claim_id)s, %(question)s,
                %(why_it_matters)s, %(priority)s, %(status)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_questions(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.questions.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        if run_id:
            return self._execute(
                "SELECT * FROM brain_research_questions WHERE ticker = %(ticker)s AND run_id = %(run_id)s ORDER BY created_at DESC",
                {"ticker": symbol, "run_id": run_id},
            )
        return self._execute(
            "SELECT * FROM brain_research_questions WHERE ticker = %(ticker)s ORDER BY created_at DESC",
            {"ticker": symbol},
        )

    def insert_news(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "news_id": row.get("news_id") or new_id("bnws"),
            "run_id": row.get("run_id"),
            "ticker": str(row["ticker"]).upper(),
            "evidence_id": row.get("evidence_id"),
            "layer": row.get("layer") or "uninterpreted",
            "title": row.get("title") or "",
            "source": row.get("source"),
            "url": row.get("url"),
            "published_at": row.get("published_at"),
            "new_fact": row.get("new_fact"),
            "affected_claim_id": row.get("affected_claim_id"),
            "impact": row.get("impact"),
            "reason": row.get("reason"),
            "financial_impact": row.get("financial_impact"),
            "quantifiable": row.get("quantifiable"),
            "claim_version_changed": bool(row.get("claim_version_changed")),
            "interpretation": dict(row.get("interpretation") or {}),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.news[stored["news_id"]] = stored
            return _copy(stored)
        payload = {**stored, "interpretation": _jsonb(stored["interpretation"])}
        out = self._one(
            """
            INSERT INTO brain_news_items (
                news_id, run_id, ticker, evidence_id, layer, title, source, url, published_at,
                new_fact, affected_claim_id, impact, reason, financial_impact, quantifiable,
                claim_version_changed, interpretation, created_at
            ) VALUES (
                %(news_id)s, %(run_id)s, %(ticker)s, %(evidence_id)s, %(layer)s, %(title)s,
                %(source)s, %(url)s, %(published_at)s, %(new_fact)s, %(affected_claim_id)s,
                %(impact)s, %(reason)s, %(financial_impact)s, %(quantifiable)s,
                %(claim_version_changed)s, %(interpretation)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_news(self, ticker: str, *, run_id: str | None = None, layer: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.news.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            if layer:
                rows = [row for row in rows if row.get("layer") == layer]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_news_items WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if run_id:
            query += " AND run_id = %(run_id)s"
            params["run_id"] = run_id
        if layer:
            query += " AND layer = %(layer)s"
            params["layer"] = layer
        query += " ORDER BY published_at DESC NULLS LAST"
        return self._execute(query, params)
