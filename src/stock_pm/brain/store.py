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
        self.evidence_sets: dict[str, dict[str, Any]] = {}
        self.candidates: dict[str, dict[str, Any]] = {}
        self.drivers: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.exposures: dict[str, dict[str, Any]] = {}
        self.history: dict[str, dict[str, Any]] = {}
        self.financial_impacts: dict[str, dict[str, Any]] = {}
        self.critic_issues: dict[str, dict[str, Any]] = {}
        self.shadows: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.causal_edges: dict[str, dict[str, Any]] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.evidence_rows: dict[str, dict[str, Any]] = {}
        self.market_attentions: dict[str, dict[str, Any]] = {}
        self.expectations: dict[str, dict[str, Any]] = {}
        self.hypotheses: dict[str, dict[str, Any]] = {}

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
            "state_key": row.get("state_key"),
            "subject": row.get("subject"),
            "qualitative_state": row.get("qualitative_state") or "",
            "current_value": row.get("current_value"),
            "related_entities": list(row.get("related_entities") or []),
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
                effective_at, expires_at, evidence_ids, source, run_id, state_key, subject,
                qualitative_state, current_value, related_entities, created_at, updated_at
            ) VALUES (
                %(state_id)s, %(ticker)s, %(state_type)s, %(name)s, %(statement)s, %(direction)s,
                %(confidence)s, %(effective_at)s, %(expires_at)s, %(evidence_ids)s, %(source)s,
                %(run_id)s, %(state_key)s, %(subject)s, %(qualitative_state)s, %(current_value)s,
                %(related_entities)s, %(created_at)s, %(updated_at)s
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

    def list_current_states(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        """Current State only. Shadow State lives in list_shadows and is never mixed in."""
        return self.list_states(ticker, run_id=run_id)

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
            "claim_key": row.get("claim_key"),
            "claim_subject": row.get("claim_subject"),
            "claim_dimension": row.get("claim_dimension"),
            "proposed_status": row.get("proposed_status") or row.get("status"),
            "lifecycle": row.get("lifecycle") or "core",
            "why_core": row.get("why_core") or "",
            "evidence_set_id": row.get("evidence_set_id"),
            "last_reviewed_at": row.get("last_reviewed_at") or _now(),
            "unverified_detail": row.get("unverified_detail") or "",
            "counter_search": dict(row.get("counter_search") or {}),
            "match_action": row.get("match_action"),
            "related_driver_ids": list(row.get("related_driver_ids") or []),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            self.claims[stored["claim_id"]] = stored
            return _copy(stored)
        payload = {**stored, "reasoning": _jsonb(stored["reasoning"]), "counter_search": _jsonb(stored["counter_search"])}
        out = self._one(
            """
            INSERT INTO brain_claims (
                claim_id, ticker, title, statement, claim_type, status, importance, confidence,
                time_horizon, why_it_matters, financial_driver, is_core, current_version_id,
                reasoning, run_id, snapshot_id, claim_key, claim_subject, claim_dimension,
                proposed_status, lifecycle, why_core, evidence_set_id, last_reviewed_at,
                unverified_detail, counter_search, match_action, related_driver_ids,
                created_at, updated_at
            ) VALUES (
                %(claim_id)s, %(ticker)s, %(title)s, %(statement)s, %(claim_type)s, %(status)s,
                %(importance)s, %(confidence)s, %(time_horizon)s, %(why_it_matters)s,
                %(financial_driver)s, %(is_core)s, %(current_version_id)s, %(reasoning)s,
                %(run_id)s, %(snapshot_id)s, %(claim_key)s, %(claim_subject)s, %(claim_dimension)s,
                %(proposed_status)s, %(lifecycle)s, %(why_core)s, %(evidence_set_id)s,
                %(last_reviewed_at)s, %(unverified_detail)s, %(counter_search)s, %(match_action)s,
                %(related_driver_ids)s, %(created_at)s, %(updated_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def update_claim_pointer(self, claim_id: str, row: dict[str, Any]) -> dict[str, Any]:
        """Point the claim at a new version. Historical statements stay on versions."""
        keys = (
            "title",
            "statement",
            "status",
            "confidence",
            "current_version_id",
            "reasoning",
            "is_core",
            "run_id",
            "snapshot_id",
            "proposed_status",
            "lifecycle",
            "why_core",
            "evidence_set_id",
            "last_reviewed_at",
            "unverified_detail",
            "counter_search",
            "match_action",
            "importance",
            "time_horizon",
            "why_it_matters",
            "financial_driver",
            "claim_subject",
            "claim_dimension",
            "claim_key",
            "related_driver_ids",
        )
        if not self._pg():
            current = dict(self.claims.get(claim_id) or {})
            for key in keys:
                if key in row:
                    current[key] = row[key]
            current["updated_at"] = _now()
            self.claims[claim_id] = current
            return _copy(current)
        payload = {
            "claim_id": claim_id,
            "title": row.get("title"),
            "statement": row.get("statement"),
            "status": row.get("status"),
            "confidence": row.get("confidence"),
            "current_version_id": row.get("current_version_id"),
            "reasoning": _jsonb(row.get("reasoning")) if "reasoning" in row else None,
            "is_core": row.get("is_core"),
            "run_id": row.get("run_id"),
            "snapshot_id": row.get("snapshot_id"),
            "proposed_status": row.get("proposed_status"),
            "lifecycle": row.get("lifecycle"),
            "why_core": row.get("why_core"),
            "evidence_set_id": row.get("evidence_set_id"),
            "last_reviewed_at": row.get("last_reviewed_at") or _now(),
            "unverified_detail": row.get("unverified_detail"),
            "counter_search": _jsonb(row.get("counter_search")) if "counter_search" in row else None,
            "match_action": row.get("match_action"),
            "importance": row.get("importance"),
            "time_horizon": row.get("time_horizon"),
            "why_it_matters": row.get("why_it_matters"),
            "financial_driver": row.get("financial_driver"),
            "claim_subject": row.get("claim_subject"),
            "claim_dimension": row.get("claim_dimension"),
            "claim_key": row.get("claim_key"),
            "related_driver_ids": row.get("related_driver_ids"),
            "updated_at": _now(),
        }
        out = self._one(
            """
            UPDATE brain_claims SET
                title = COALESCE(%(title)s, title),
                statement = COALESCE(%(statement)s, statement),
                status = COALESCE(%(status)s, status),
                confidence = COALESCE(%(confidence)s, confidence),
                current_version_id = COALESCE(%(current_version_id)s, current_version_id),
                reasoning = COALESCE(%(reasoning)s, reasoning),
                is_core = COALESCE(%(is_core)s, is_core),
                run_id = COALESCE(%(run_id)s, run_id),
                snapshot_id = COALESCE(%(snapshot_id)s, snapshot_id),
                proposed_status = COALESCE(%(proposed_status)s, proposed_status),
                lifecycle = COALESCE(%(lifecycle)s, lifecycle),
                why_core = COALESCE(%(why_core)s, why_core),
                evidence_set_id = COALESCE(%(evidence_set_id)s, evidence_set_id),
                last_reviewed_at = COALESCE(%(last_reviewed_at)s, last_reviewed_at),
                unverified_detail = COALESCE(%(unverified_detail)s, unverified_detail),
                counter_search = COALESCE(%(counter_search)s, counter_search),
                match_action = COALESCE(%(match_action)s, match_action),
                importance = COALESCE(%(importance)s, importance),
                time_horizon = COALESCE(%(time_horizon)s, time_horizon),
                why_it_matters = COALESCE(%(why_it_matters)s, why_it_matters),
                financial_driver = COALESCE(%(financial_driver)s, financial_driver),
                claim_subject = COALESCE(%(claim_subject)s, claim_subject),
                claim_dimension = COALESCE(%(claim_dimension)s, claim_dimension),
                claim_key = COALESCE(%(claim_key)s, claim_key),
                related_driver_ids = COALESCE(%(related_driver_ids)s, related_driver_ids),
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

    def list_active_claims(self, ticker: str) -> list[dict[str, Any]]:
        rows = self.list_claims(ticker)
        return [row for row in rows if str(row.get("lifecycle") or "core") != "closed"]

    def get_claim_by_key(self, ticker: str, claim_key: str) -> dict[str, Any] | None:
        if not claim_key:
            return None
        if not self._pg():
            for row in self.claims.values():
                if row.get("ticker") == ticker.upper() and row.get("claim_key") == claim_key:
                    return _copy(row)
            return None
        return self._one(
            "SELECT * FROM brain_claims WHERE ticker = %(ticker)s AND claim_key = %(claim_key)s LIMIT 1",
            {"ticker": ticker.upper(), "claim_key": claim_key},
        )

    def insert_version(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "claim_version_id": row.get("claim_version_id") or new_id("bclv"),
            "claim_id": row["claim_id"],
            "version": int(row.get("version") or 1),
            "statement": row.get("statement") or row.get("new_statement") or "",
            "status": row.get("status") or row.get("new_status") or "emerging",
            "confidence": row.get("confidence") or row.get("new_confidence") or "low",
            "reason_for_change": row.get("reason_for_change") or "",
            "added_evidence_ids": list(row.get("added_evidence_ids") or []),
            "removed_evidence_ids": list(row.get("removed_evidence_ids") or []),
            "counter_evidence_ids": list(row.get("counter_evidence_ids") or []),
            "old_statement": row.get("old_statement"),
            "new_statement": row.get("new_statement") or row.get("statement"),
            "old_status": row.get("old_status"),
            "new_status": row.get("new_status") or row.get("status"),
            "old_confidence": row.get("old_confidence"),
            "new_confidence": row.get("new_confidence") or row.get("confidence"),
            "added_counter_evidence_ids": list(row.get("added_counter_evidence_ids") or []),
            "triggering_document_ids": list(row.get("triggering_document_ids") or []),
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
                old_statement, new_statement, old_status, new_status, old_confidence, new_confidence,
                added_counter_evidence_ids, triggering_document_ids, snapshot_id, run_id, created_at
            ) VALUES (
                %(claim_version_id)s, %(claim_id)s, %(version)s, %(statement)s, %(status)s,
                %(confidence)s, %(reason_for_change)s, %(added_evidence_ids)s, %(removed_evidence_ids)s,
                %(counter_evidence_ids)s, %(old_statement)s, %(new_statement)s, %(old_status)s,
                %(new_status)s, %(old_confidence)s, %(new_confidence)s, %(added_counter_evidence_ids)s,
                %(triggering_document_ids)s, %(snapshot_id)s, %(run_id)s, %(created_at)s
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
            "claim_version_id": row.get("claim_version_id"),
            "source_relationship": row.get("source_relationship") or "unknown",
            "incomplete": bool(row.get("incomplete")),
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
                reason, proves, does_not_prove, claim_version_id, source_relationship,
                incomplete, run_id, created_at
            ) VALUES (
                %(link_id)s, %(claim_id)s, %(evidence_id)s, %(direction)s, %(strength)s,
                %(relevance)s, %(reason)s, %(proves)s, %(does_not_prove)s, %(claim_version_id)s,
                %(source_relationship)s, %(incomplete)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_links(
        self,
        *,
        claim_id: str | None = None,
        evidence_id: str | None = None,
        claim_version_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._pg():
            rows = list(self.links)
            if claim_id:
                rows = [row for row in rows if row.get("claim_id") == claim_id]
            if evidence_id:
                rows = [row for row in rows if row.get("evidence_id") == evidence_id]
            if claim_version_id:
                rows = [row for row in rows if row.get("claim_version_id") == claim_version_id]
            return [_copy(row) for row in rows]
        clauses = []
        params: dict[str, Any] = {}
        if claim_id:
            clauses.append("claim_id = %(claim_id)s")
            params["claim_id"] = claim_id
        if evidence_id:
            clauses.append("evidence_id = %(evidence_id)s")
            params["evidence_id"] = evidence_id
        if claim_version_id:
            clauses.append("claim_version_id = %(claim_version_id)s")
            params["claim_version_id"] = claim_version_id
        if not clauses:
            return []
        return self._execute(
            "SELECT * FROM brain_claim_evidence_links WHERE " + " AND ".join(clauses),
            params,
        )

    def insert_evidence_set(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "evidence_set_id": row.get("evidence_set_id") or new_id("bes"),
            "run_id": row.get("run_id"),
            "ticker": str(row.get("ticker") or "").upper(),
            "payload": dict(row.get("payload") or row),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.evidence_sets[stored["evidence_set_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_evidence_sets (evidence_set_id, run_id, ticker, payload, created_at)
            VALUES (%(evidence_set_id)s, %(run_id)s, %(ticker)s, %(payload)s, %(created_at)s)
            RETURNING *
            """,
            {**stored, "payload": _jsonb(stored["payload"])},
        )
        assert out is not None
        return out

    def latest_evidence_set(self, ticker: str, *, run_id: str | None = None) -> dict[str, Any] | None:
        symbol = str(ticker or "").upper()
        if not self._pg():
            rows = [row for row in self.evidence_sets.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return _copy(rows[0]) if rows else None
        if run_id:
            return self._one(
                """
                SELECT * FROM brain_evidence_sets
                WHERE ticker = %(ticker)s AND run_id = %(run_id)s
                ORDER BY created_at DESC LIMIT 1
                """,
                {"ticker": symbol, "run_id": run_id},
            )
        return self._one(
            """
            SELECT * FROM brain_evidence_sets
            WHERE ticker = %(ticker)s
            ORDER BY created_at DESC LIMIT 1
            """,
            {"ticker": symbol},
        )

    def upsert_evidence(self, row: dict[str, Any]) -> dict[str, Any]:
        eid = str(row.get("id") or row.get("evidence_id") or new_id("rev"))
        stored = {
            "id": eid,
            "evidence_id": eid,
            "ticker": str(row.get("ticker") or "").upper() or None,
            "title": row.get("title") or "",
            "fact": row.get("fact") or row.get("statement") or row.get("excerpt") or "",
            "statement": row.get("statement") or row.get("fact") or "",
            "excerpt": row.get("excerpt") or row.get("fact") or "",
            "source": row.get("source"),
            "direction": row.get("direction"),
            "url": row.get("url"),
        }
        self.evidence_rows[eid] = stored
        return _copy(stored)

    def list_evidence(self, ticker: str | None = None) -> list[dict[str, Any]]:
        symbol = str(ticker or "").upper()
        rows = [_copy(row) for row in self.evidence_rows.values()]
        if symbol:
            rows = [row for row in rows if not row.get("ticker") or row.get("ticker") == symbol]
        frozen = self.latest_evidence_set(symbol) if symbol else None
        payload = dict((frozen or {}).get("payload") or {})
        extra = payload.get("evidence") or payload.get("items") or payload.get("rows") or []
        seen = {str(row.get("id") or row.get("evidence_id") or "") for row in rows}
        for item in extra:
            if not isinstance(item, dict):
                continue
            eid = str(item.get("id") or item.get("evidence_id") or "")
            if not eid or eid in seen:
                continue
            rows.append(
                {
                    "id": eid,
                    "evidence_id": eid,
                    "ticker": symbol or None,
                    "title": item.get("title") or "",
                    "fact": item.get("fact") or item.get("statement") or item.get("excerpt") or "",
                    "statement": item.get("statement") or item.get("fact") or "",
                    "excerpt": item.get("excerpt") or item.get("fact") or "",
                    "source": item.get("source"),
                }
            )
            seen.add(eid)
        return rows

    def insert_candidate(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "candidate_id": row.get("candidate_id") or new_id("bcc"),
            "run_id": row.get("run_id"),
            "ticker": str(row.get("ticker") or "").upper(),
            "title": row.get("title") or "",
            "statement": row.get("statement") or "",
            "selected_as_core": bool(row.get("selected_as_core")),
            "why_core": row.get("why_core") or "",
            "why_not_core": row.get("why_not_core") or "",
            "scores": dict(row.get("scores") or {}),
            "supporting_evidence_ids": list(row.get("supporting_evidence_ids") or []),
            "opposing_evidence_ids": list(row.get("opposing_evidence_ids") or []),
            "missing_evidence": list(row.get("missing_evidence") or []),
            "claim_id": row.get("claim_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.candidates[stored["candidate_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_claim_candidates (
                candidate_id, run_id, ticker, title, statement, selected_as_core, why_core,
                why_not_core, scores, supporting_evidence_ids, opposing_evidence_ids,
                missing_evidence, claim_id, created_at
            ) VALUES (
                %(candidate_id)s, %(run_id)s, %(ticker)s, %(title)s, %(statement)s,
                %(selected_as_core)s, %(why_core)s, %(why_not_core)s, %(scores)s,
                %(supporting_evidence_ids)s, %(opposing_evidence_ids)s, %(missing_evidence)s,
                %(claim_id)s, %(created_at)s
            ) RETURNING *
            """,
            {**stored, "scores": _jsonb(stored["scores"])},
        )
        assert out is not None
        return out

    def list_candidates(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.candidates.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        if run_id:
            return self._execute(
                "SELECT * FROM brain_claim_candidates WHERE ticker = %(ticker)s AND run_id = %(run_id)s",
                {"ticker": symbol, "run_id": run_id},
            )
        return self._execute(
            "SELECT * FROM brain_claim_candidates WHERE ticker = %(ticker)s",
            {"ticker": symbol},
        )

    def insert_question(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "question_id": row.get("question_id") or new_id("brq"),
            "ticker": str(row["ticker"]).upper(),
            "related_claim_id": row.get("related_claim_id"),
            "question": row.get("question") or "",
            "why_it_matters": row.get("why_it_matters") or "",
            "priority": row.get("priority") or "medium",
            "status": row.get("status") or "open",
            "related_objects": list(row.get("related_objects") or []),
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
                priority, status, related_objects, run_id, created_at
            ) VALUES (
                %(question_id)s, %(ticker)s, %(related_claim_id)s, %(question)s,
                %(why_it_matters)s, %(priority)s, %(status)s, %(related_objects)s,
                %(run_id)s, %(created_at)s
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

    def insert_driver(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "driver_id": row.get("driver_id") or new_id("bdrv"),
            "ticker": str(row["ticker"]).upper(),
            "canonical_key": row.get("canonical_key") or "",
            "driver_key": row.get("driver_key"),
            "name": row.get("name") or "",
            "description": row.get("description") or "",
            "category": row.get("category") or "demand",
            "financial_link": row.get("financial_link"),
            "time_horizon": row.get("time_horizon"),
            "current_state": row.get("current_state") or "",
            "direction": row.get("direction"),
            "importance": row.get("importance") or "medium",
            "uncertainty": row.get("uncertainty") or "medium",
            "persistence": row.get("persistence") or "medium",
            "reversibility": row.get("reversibility"),
            "why_it_matters": row.get("why_it_matters") or "",
            "evidence_ids": list(row.get("evidence_ids") or []),
            "related_claim_ids": list(row.get("related_claim_ids") or []),
            "related_entity_ids": list(row.get("related_entity_ids") or []),
            "missing_evidence": list(row.get("missing_evidence") or []),
            "status": row.get("status") or "active",
            "match_action": row.get("match_action"),
            "run_id": row.get("run_id"),
            "last_updated_at": row.get("last_updated_at") or _now(),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            self.drivers[stored["driver_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_value_drivers (
                driver_id, ticker, canonical_key, driver_key, name, description, category,
                financial_link, time_horizon, current_state, direction, importance, uncertainty,
                persistence, reversibility, why_it_matters, evidence_ids, related_claim_ids,
                related_entity_ids, missing_evidence, status, match_action, run_id,
                last_updated_at, created_at, updated_at
            ) VALUES (
                %(driver_id)s, %(ticker)s, %(canonical_key)s, %(driver_key)s, %(name)s,
                %(description)s, %(category)s, %(financial_link)s, %(time_horizon)s,
                %(current_state)s, %(direction)s, %(importance)s, %(uncertainty)s,
                %(persistence)s, %(reversibility)s, %(why_it_matters)s, %(evidence_ids)s,
                %(related_claim_ids)s, %(related_entity_ids)s, %(missing_evidence)s,
                %(status)s, %(match_action)s, %(run_id)s, %(last_updated_at)s,
                %(created_at)s, %(updated_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def update_driver(self, driver_id: str, row: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "name",
            "description",
            "category",
            "financial_link",
            "time_horizon",
            "current_state",
            "direction",
            "importance",
            "uncertainty",
            "persistence",
            "reversibility",
            "why_it_matters",
            "evidence_ids",
            "related_claim_ids",
            "related_entity_ids",
            "missing_evidence",
            "status",
            "match_action",
            "run_id",
            "canonical_key",
            "driver_key",
        )
        if not self._pg():
            current = dict(self.drivers.get(driver_id) or {})
            for key in keys:
                if key in row:
                    current[key] = row[key]
            current["last_updated_at"] = row.get("last_updated_at") or _now()
            current["updated_at"] = _now()
            self.drivers[driver_id] = current
            return _copy(current)
        payload = {key: row.get(key) for key in keys}
        payload["driver_id"] = driver_id
        payload["last_updated_at"] = row.get("last_updated_at") or _now()
        payload["updated_at"] = _now()
        out = self._one(
            """
            UPDATE brain_value_drivers SET
                name = COALESCE(%(name)s, name),
                description = COALESCE(%(description)s, description),
                category = COALESCE(%(category)s, category),
                financial_link = COALESCE(%(financial_link)s, financial_link),
                time_horizon = COALESCE(%(time_horizon)s, time_horizon),
                current_state = COALESCE(%(current_state)s, current_state),
                direction = COALESCE(%(direction)s, direction),
                importance = COALESCE(%(importance)s, importance),
                uncertainty = COALESCE(%(uncertainty)s, uncertainty),
                persistence = COALESCE(%(persistence)s, persistence),
                reversibility = COALESCE(%(reversibility)s, reversibility),
                why_it_matters = COALESCE(%(why_it_matters)s, why_it_matters),
                evidence_ids = COALESCE(%(evidence_ids)s, evidence_ids),
                related_claim_ids = COALESCE(%(related_claim_ids)s, related_claim_ids),
                related_entity_ids = COALESCE(%(related_entity_ids)s, related_entity_ids),
                missing_evidence = COALESCE(%(missing_evidence)s, missing_evidence),
                status = COALESCE(%(status)s, status),
                match_action = COALESCE(%(match_action)s, match_action),
                run_id = COALESCE(%(run_id)s, run_id),
                canonical_key = COALESCE(%(canonical_key)s, canonical_key),
                driver_key = COALESCE(%(driver_key)s, driver_key),
                last_updated_at = %(last_updated_at)s,
                updated_at = %(updated_at)s
            WHERE driver_id = %(driver_id)s
            RETURNING *
            """,
            payload,
        )
        return out or {}

    def get_driver(self, driver_id: str) -> dict[str, Any] | None:
        if not self._pg():
            row = self.drivers.get(driver_id)
            return _copy(row) if row else None
        return self._one(
            "SELECT * FROM brain_value_drivers WHERE driver_id = %(driver_id)s",
            {"driver_id": driver_id},
        )

    def get_driver_by_key(self, ticker: str, canonical_key: str) -> dict[str, Any] | None:
        if not canonical_key:
            return None
        if not self._pg():
            for row in self.drivers.values():
                if row.get("ticker") == ticker.upper() and row.get("canonical_key") == canonical_key:
                    return _copy(row)
            return None
        return self._one(
            """
            SELECT * FROM brain_value_drivers
            WHERE ticker = %(ticker)s AND canonical_key = %(canonical_key)s
            LIMIT 1
            """,
            {"ticker": ticker.upper(), "canonical_key": canonical_key},
        )

    def list_drivers(self, ticker: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.drivers.values() if row.get("ticker") == symbol]
            if active_only:
                rows = [row for row in rows if str(row.get("status") or "active") not in {"closed", "retired"}]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_value_drivers WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if active_only:
            query += " AND status IS DISTINCT FROM 'closed' AND status IS DISTINCT FROM 'retired'"
        query += " ORDER BY importance DESC, updated_at DESC"
        return self._execute(query, params)

    def upsert_driver(self, row: dict[str, Any]) -> dict[str, Any]:
        existing = None
        if row.get("driver_id"):
            existing = self.get_driver(str(row["driver_id"]))
        if existing is None:
            existing = self.get_driver_by_key(str(row.get("ticker") or ""), str(row.get("canonical_key") or ""))
        if existing:
            updated = self.update_driver(existing["driver_id"], {**row, "match_action": row.get("match_action") or "update_existing"})
            updated["match_action"] = "update_existing"
            return updated
        return self.insert_driver({**row, "match_action": row.get("match_action") or "create_new"})

    def get_state_by_key(self, ticker: str, state_key: str) -> dict[str, Any] | None:
        if not state_key:
            return None
        if not self._pg():
            for row in self.states.values():
                if row.get("ticker") == ticker.upper() and row.get("state_key") == state_key:
                    return _copy(row)
            return None
        return self._one(
            "SELECT * FROM brain_states WHERE ticker = %(ticker)s AND state_key = %(state_key)s LIMIT 1",
            {"ticker": ticker.upper(), "state_key": state_key},
        )

    def upsert_state(self, row: dict[str, Any]) -> dict[str, Any]:
        existing = None
        if row.get("state_id"):
            existing = self._one("SELECT * FROM brain_states WHERE state_id = %(state_id)s", {"state_id": row["state_id"]}) if self._pg() else _copy(self.states.get(str(row["state_id"])))
        if existing is None and row.get("state_key"):
            existing = self.get_state_by_key(str(row.get("ticker") or ""), str(row.get("state_key")))
        if existing:
            merged = {**existing, **row, "state_id": existing["state_id"], "updated_at": _now()}
            if not self._pg():
                self.states[existing["state_id"]] = merged
                return _copy(merged)
            return self.insert_state({**merged, "state_id": existing["state_id"]}) if False else self._update_state(existing["state_id"], merged)
        return self.insert_state(row)

    def _update_state(self, state_id: str, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "state_id": state_id,
            "name": row.get("name"),
            "statement": row.get("statement"),
            "direction": row.get("direction"),
            "confidence": row.get("confidence"),
            "evidence_ids": row.get("evidence_ids"),
            "qualitative_state": row.get("qualitative_state"),
            "current_value": row.get("current_value"),
            "related_entities": row.get("related_entities"),
            "updated_at": _now(),
        }
        out = self._one(
            """
            UPDATE brain_states SET
                name = COALESCE(%(name)s, name),
                statement = COALESCE(%(statement)s, statement),
                direction = COALESCE(%(direction)s, direction),
                confidence = COALESCE(%(confidence)s, confidence),
                evidence_ids = COALESCE(%(evidence_ids)s, evidence_ids),
                qualitative_state = COALESCE(%(qualitative_state)s, qualitative_state),
                current_value = COALESCE(%(current_value)s, current_value),
                related_entities = COALESCE(%(related_entities)s, related_entities),
                updated_at = %(updated_at)s
            WHERE state_id = %(state_id)s
            RETURNING *
            """,
            payload,
        )
        return out or {}

    def insert_event(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "event_id": row.get("event_id") or new_id("bev"),
            "ticker": str(row["ticker"]).upper(),
            "event_type": row.get("event_type") or "other",
            "subject": row.get("subject") or "",
            "title": row.get("title") or "",
            "event_date": row.get("event_date"),
            "entities": list(row.get("entities") or []),
            "evidence_ids": list(row.get("evidence_ids") or []),
            "confidence": row.get("confidence"),
            "materiality": row.get("materiality") or "context",
            "novelty": row.get("novelty"),
            "source_quality": row.get("source_quality"),
            "fact_reliability": row.get("fact_reliability"),
            "decision_targets": list(row.get("decision_targets") or []),
            "affected_states": list(row.get("affected_states") or []),
            "affected_drivers": list(row.get("affected_drivers") or []),
            "affected_claims": list(row.get("affected_claims") or []),
            "transmission": dict(row.get("transmission") or {}),
            "financial_impact": dict(row.get("financial_impact") or {}),
            "scenario_impact": dict(row.get("scenario_impact") or {}),
            "fingerprint": row.get("fingerprint"),
            "url": row.get("url"),
            "reason": row.get("reason") or "",
            "run_id": row.get("run_id"),
            "duplicate": bool(row.get("duplicate")),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.events[stored["event_id"]] = stored
            return _copy(stored)
        payload = {
            **stored,
            "transmission": _jsonb(stored["transmission"]),
            "financial_impact": _jsonb(stored["financial_impact"]),
            "scenario_impact": _jsonb(stored["scenario_impact"]),
        }
        payload.pop("duplicate", None)
        out = self._one(
            """
            INSERT INTO brain_events (
                event_id, ticker, event_type, subject, title, event_date, entities, evidence_ids,
                confidence, materiality, novelty, source_quality, fact_reliability, decision_targets,
                affected_states, affected_drivers, affected_claims, transmission, financial_impact,
                scenario_impact, fingerprint, url, reason, run_id, created_at
            ) VALUES (
                %(event_id)s, %(ticker)s, %(event_type)s, %(subject)s, %(title)s, %(event_date)s,
                %(entities)s, %(evidence_ids)s, %(confidence)s, %(materiality)s, %(novelty)s,
                %(source_quality)s, %(fact_reliability)s, %(decision_targets)s, %(affected_states)s,
                %(affected_drivers)s, %(affected_claims)s, %(transmission)s, %(financial_impact)s,
                %(scenario_impact)s, %(fingerprint)s, %(url)s, %(reason)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_events(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.events.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_events WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if run_id:
            query += " AND run_id = %(run_id)s"
            params["run_id"] = run_id
        query += " ORDER BY created_at DESC"
        return self._execute(query, params)

    def get_event_by_fingerprint(self, ticker: str, fingerprint: str) -> dict[str, Any] | None:
        if not fingerprint:
            return None
        if not self._pg():
            for row in self.events.values():
                if row.get("ticker") == ticker.upper() and row.get("fingerprint") == fingerprint:
                    return _copy(row)
            return None
        return self._one(
            "SELECT * FROM brain_events WHERE ticker = %(ticker)s AND fingerprint = %(fingerprint)s LIMIT 1",
            {"ticker": ticker.upper(), "fingerprint": fingerprint},
        )

    def insert_exposure(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "exposure_id": row.get("exposure_id") or new_id("bexp"),
            "ticker": str(row["ticker"]).upper(),
            "state_or_event": row.get("state_or_event"),
            "event_id": row.get("event_id"),
            "state_id": row.get("state_id"),
            "exposure_type": row.get("exposure_type") or "financial",
            "direction": row.get("direction"),
            "magnitude": row.get("magnitude"),
            "direct_or_indirect": row.get("direct_or_indirect"),
            "evidence_ids": list(row.get("evidence_ids") or []),
            "uncertainty": row.get("uncertainty"),
            "related_only": bool(row.get("related_only")),
            "can_affect_claim": bool(row.get("can_affect_claim")),
            "reason": row.get("reason") or "",
            "subject": row.get("subject") or str(row.get("ticker") or "").upper(),
            "object_name": row.get("object_name") or row.get("object") or "",
            "mechanism": row.get("mechanism") or row.get("reason") or "",
            "related_driver_id": row.get("related_driver_id"),
            "related_claim_id": row.get("related_claim_id"),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.exposures[stored["exposure_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_exposures (
                exposure_id, ticker, state_or_event, event_id, state_id, exposure_type, direction,
                magnitude, direct_or_indirect, evidence_ids, uncertainty, related_only,
                can_affect_claim, reason, subject, object_name, mechanism, related_driver_id,
                related_claim_id, run_id, created_at
            ) VALUES (
                %(exposure_id)s, %(ticker)s, %(state_or_event)s, %(event_id)s, %(state_id)s,
                %(exposure_type)s, %(direction)s, %(magnitude)s, %(direct_or_indirect)s,
                %(evidence_ids)s, %(uncertainty)s, %(related_only)s, %(can_affect_claim)s,
                %(reason)s, %(subject)s, %(object_name)s, %(mechanism)s, %(related_driver_id)s,
                %(related_claim_id)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_exposures(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.exposures.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_exposures WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if run_id:
            query += " AND run_id = %(run_id)s"
            params["run_id"] = run_id
        query += " ORDER BY created_at DESC"
        return self._execute(query, params)

    def insert_financial_impact(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "impact_id": row.get("impact_id") or new_id("bfi"),
            "ticker": str(row["ticker"]).upper(),
            "object_type": row.get("object_type") or "driver",
            "object_id": row.get("object_id") or "",
            "metric": row.get("metric") or "",
            "direction": row.get("direction"),
            "magnitude_range": row.get("magnitude_range"),
            "time_horizon": row.get("time_horizon"),
            "confidence": row.get("confidence"),
            "mechanism": row.get("mechanism") or "",
            "evidence_ids": list(row.get("evidence_ids") or []),
            "direction_only": bool(row.get("direction_only", True)),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.financial_impacts[stored["impact_id"]] = stored
            return _copy(stored)
        payload = {**stored, "magnitude_range": _jsonb(stored["magnitude_range"])}
        out = self._one(
            """
            INSERT INTO brain_financial_impacts (
                impact_id, ticker, object_type, object_id, metric, direction, magnitude_range,
                time_horizon, confidence, mechanism, evidence_ids, direction_only, run_id, created_at
            ) VALUES (
                %(impact_id)s, %(ticker)s, %(object_type)s, %(object_id)s, %(metric)s, %(direction)s,
                %(magnitude_range)s, %(time_horizon)s, %(confidence)s, %(mechanism)s, %(evidence_ids)s,
                %(direction_only)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_financial_impacts(self, ticker: str, *, run_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.financial_impacts.values() if row.get("ticker") == symbol]
            if run_id:
                rows = [row for row in rows if row.get("run_id") == run_id]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_financial_impacts WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if run_id:
            query += " AND run_id = %(run_id)s"
            params["run_id"] = run_id
        return self._execute(query, params)

    def insert_history(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "history_id": row.get("history_id") or new_id("bhis"),
            "ticker": str(row["ticker"]).upper(),
            "object_type": row.get("object_type") or "",
            "object_id": row.get("object_id") or "",
            "from_payload": dict(row.get("from_payload") or {}),
            "to_payload": dict(row.get("to_payload") or {}),
            "reason": row.get("reason") or "",
            "event_id": row.get("event_id"),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.history[stored["history_id"]] = stored
            return _copy(stored)
        payload = {**stored, "from_payload": _jsonb(stored["from_payload"]), "to_payload": _jsonb(stored["to_payload"])}
        out = self._one(
            """
            INSERT INTO brain_history (
                history_id, ticker, object_type, object_id, from_payload, to_payload,
                reason, event_id, run_id, created_at
            ) VALUES (
                %(history_id)s, %(ticker)s, %(object_type)s, %(object_id)s, %(from_payload)s,
                %(to_payload)s, %(reason)s, %(event_id)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_history(self, ticker: str, *, object_type: str | None = None, object_id: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.history.values() if row.get("ticker") == symbol]
            if object_type:
                rows = [row for row in rows if row.get("object_type") == object_type]
            if object_id:
                rows = [row for row in rows if row.get("object_id") == object_id]
            rows.sort(key=lambda item: str(item.get("created_at") or ""))
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_history WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if object_type:
            query += " AND object_type = %(object_type)s"
            params["object_type"] = object_type
        if object_id:
            query += " AND object_id = %(object_id)s"
            params["object_id"] = object_id
        query += " ORDER BY created_at"
        return self._execute(query, params)

    def upsert_shadow(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "shadow_id": row.get("shadow_id") or new_id("bshd"),
            "ticker": str(row["ticker"]).upper(),
            "name": row.get("name") or "unconfirmed_signal",
            "statement": row.get("statement") or "",
            "confidence": row.get("confidence") or "low",
            "materiality_if_true": row.get("materiality_if_true") or "high",
            "status": row.get("status") or "open",
            "evidence_ids": list(row.get("evidence_ids") or []),
            "related_object_ids": list(row.get("related_object_ids") or []),
            "source_kind": row.get("source_kind") or "signal",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            for existing in self.shadows.values():
                if existing.get("ticker") == stored["ticker"] and existing.get("name") == stored["name"]:
                    stored["shadow_id"] = existing["shadow_id"]
                    stored["created_at"] = existing.get("created_at") or stored["created_at"]
                    self.shadows[stored["shadow_id"]] = stored
                    return _copy(stored)
            self.shadows[stored["shadow_id"]] = stored
            return _copy(stored)
        payload = {
            **stored,
            "evidence_ids": stored["evidence_ids"],
            "related_object_ids": stored["related_object_ids"],
        }
        out = self._one(
            """
            INSERT INTO brain_shadow_states (
                shadow_id, ticker, name, statement, confidence, materiality_if_true, status,
                evidence_ids, related_object_ids, source_kind, run_id, created_at, updated_at
            ) VALUES (
                %(shadow_id)s, %(ticker)s, %(name)s, %(statement)s, %(confidence)s,
                %(materiality_if_true)s, %(status)s, %(evidence_ids)s, %(related_object_ids)s,
                %(source_kind)s, %(run_id)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (ticker, name) DO UPDATE SET
                statement = EXCLUDED.statement,
                confidence = EXCLUDED.confidence,
                materiality_if_true = EXCLUDED.materiality_if_true,
                status = EXCLUDED.status,
                evidence_ids = EXCLUDED.evidence_ids,
                related_object_ids = EXCLUDED.related_object_ids,
                source_kind = EXCLUDED.source_kind,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_shadows(self, ticker: str, *, status: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.shadows.values() if row.get("ticker") == symbol]
            if status:
                rows = [row for row in rows if row.get("status") == status]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_shadow_states WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if status:
            query += " AND status = %(status)s"
            params["status"] = status
        query += " ORDER BY updated_at DESC"
        return self._execute(query, params)

    def insert_proposal(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "proposal_id": row.get("proposal_id") or new_id("bcpr"),
            "ticker": str(row["ticker"]).upper(),
            "object_type": row.get("object_type") or "",
            "object_id": row.get("object_id") or "",
            "from_payload": dict(row.get("from_payload") or {}),
            "to_payload": dict(row.get("to_payload") or {}),
            "reason": row.get("reason") or "",
            "evidence_ids": list(row.get("evidence_ids") or []),
            "source_kind": row.get("source_kind") or "news",
            "decision": row.get("decision") or "requires_review",
            "rules": list(row.get("rules") or []),
            "reason_code": row.get("reason_code") or "",
            "related_objects": list(row.get("related_objects") or []),
            "layer": row.get("layer") or "",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.proposals[stored["proposal_id"]] = stored
            return _copy(stored)
        payload = {
            **stored,
            "from_payload": _jsonb(stored["from_payload"]),
            "to_payload": _jsonb(stored["to_payload"]),
            "rules": _jsonb(stored["rules"]),
        }
        out = self._one(
            """
            INSERT INTO brain_change_proposals (
                proposal_id, ticker, object_type, object_id, from_payload, to_payload, reason,
                evidence_ids, source_kind, decision, rules, reason_code, related_objects, layer, run_id, created_at
            ) VALUES (
                %(proposal_id)s, %(ticker)s, %(object_type)s, %(object_id)s, %(from_payload)s,
                %(to_payload)s, %(reason)s, %(evidence_ids)s, %(source_kind)s, %(decision)s,
                %(rules)s, %(reason_code)s, %(related_objects)s, %(layer)s, %(run_id)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_proposals(self, ticker: str, *, decision: str | None = None) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            rows = [row for row in self.proposals.values() if row.get("ticker") == symbol]
            if decision:
                rows = [row for row in rows if row.get("decision") == decision]
            return [_copy(row) for row in rows]
        query = "SELECT * FROM brain_change_proposals WHERE ticker = %(ticker)s"
        params: dict[str, Any] = {"ticker": symbol}
        if decision:
            query += " AND decision = %(decision)s"
            params["decision"] = decision
        query += " ORDER BY created_at DESC"
        return self._execute(query, params)

    def upsert_causal_edge(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "edge_id": row.get("edge_id") or new_id("bced"),
            "ticker": str(row["ticker"]).upper(),
            "from_node": row.get("from_node") or "",
            "to_node": row.get("to_node") or "",
            "from_type": row.get("from_type") or "",
            "to_type": row.get("to_type") or "",
            "relationship_type": row.get("relationship_type") or "other",
            "mechanism": row.get("mechanism") or row.get("statement") or "",
            "statement": row.get("statement") or row.get("mechanism") or "",
            "direction": row.get("direction") or "positive",
            "strength": row.get("strength") or "medium",
            "confidence": row.get("confidence") or "low",
            "time_horizon": row.get("time_horizon") or "medium",
            "lag": row.get("lag") or "unknown",
            "conditions": row.get("conditions") or "",
            "status": row.get("status") or "candidate",
            "evidence_ids": list(row.get("evidence_ids") or row.get("support_evidence_ids") or []),
            "support_evidence_ids": list(row.get("support_evidence_ids") or row.get("evidence_ids") or []),
            "counter_evidence_ids": list(row.get("counter_evidence_ids") or []),
            "support_strength": int(row.get("support_strength") or 0),
            "counter_strength": int(row.get("counter_strength") or 0),
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        existing = None
        if not self._pg():
            for existing_row in self.causal_edges.values():
                if (
                    existing_row.get("ticker") == stored["ticker"]
                    and existing_row.get("from_node") == stored["from_node"]
                    and existing_row.get("to_node") == stored["to_node"]
                ):
                    existing = existing_row
                    break
        else:
            existing = self._one(
                """
                SELECT * FROM brain_causal_edges
                WHERE ticker = %(ticker)s AND from_node = %(from_node)s AND to_node = %(to_node)s
                LIMIT 1
                """,
                {"ticker": stored["ticker"], "from_node": stored["from_node"], "to_node": stored["to_node"]},
            )
        if existing:
            stored["edge_id"] = existing["edge_id"]
            stored["created_at"] = existing.get("created_at") or stored["created_at"]
            stored["support_evidence_ids"] = list(
                dict.fromkeys(list(existing.get("support_evidence_ids") or []) + stored["support_evidence_ids"])
            )
            stored["counter_evidence_ids"] = list(
                dict.fromkeys(list(existing.get("counter_evidence_ids") or []) + stored["counter_evidence_ids"])
            )
            stored["evidence_ids"] = list(dict.fromkeys(list(existing.get("evidence_ids") or []) + stored["evidence_ids"]))
            stored["support_strength"] = max(int(existing.get("support_strength") or 0), stored["support_strength"])
            stored["counter_strength"] = max(int(existing.get("counter_strength") or 0), stored["counter_strength"])
        if not self._pg():
            self.causal_edges[stored["edge_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_causal_edges (
                edge_id, ticker, from_node, to_node, from_type, to_type, relationship_type,
                mechanism, statement, direction, strength, confidence, time_horizon, lag,
                conditions, status, evidence_ids, support_evidence_ids, counter_evidence_ids,
                support_strength, counter_strength, run_id, created_at, updated_at
            ) VALUES (
                %(edge_id)s, %(ticker)s, %(from_node)s, %(to_node)s, %(from_type)s, %(to_type)s,
                %(relationship_type)s, %(mechanism)s, %(statement)s, %(direction)s, %(strength)s,
                %(confidence)s, %(time_horizon)s, %(lag)s, %(conditions)s, %(status)s,
                %(evidence_ids)s, %(support_evidence_ids)s, %(counter_evidence_ids)s,
                %(support_strength)s, %(counter_strength)s, %(run_id)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (ticker, from_node, to_node) DO UPDATE SET
                statement = EXCLUDED.statement,
                mechanism = EXCLUDED.mechanism,
                status = EXCLUDED.status,
                direction = EXCLUDED.direction,
                strength = EXCLUDED.strength,
                confidence = EXCLUDED.confidence,
                evidence_ids = EXCLUDED.evidence_ids,
                support_evidence_ids = EXCLUDED.support_evidence_ids,
                counter_evidence_ids = EXCLUDED.counter_evidence_ids,
                support_strength = EXCLUDED.support_strength,
                counter_strength = EXCLUDED.counter_strength,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_causal_edges(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            return [_copy(row) for row in self.causal_edges.values() if row.get("ticker") == symbol]
        return self._execute(
            "SELECT * FROM brain_causal_edges WHERE ticker = %(ticker)s ORDER BY created_at",
            {"ticker": symbol},
        )

    def insert_observation(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "observation_id": row.get("observation_id") or new_id("bobs"),
            "ticker": str(row["ticker"]).upper(),
            "title": row.get("title") or "",
            "statement": row.get("statement") or row.get("fact") or "",
            "kind": row.get("kind") or "news",
            "material": bool(row.get("material")),
            "reason": row.get("reason") or "",
            "fingerprint": row.get("fingerprint") or "",
            "payload": dict(row.get("payload") or {}),
            "created_at": row.get("created_at") or _now(),
        }
        if not self._pg():
            self.observations[stored["observation_id"]] = stored
            return _copy(stored)
        payload = {**stored, "payload": _jsonb(stored["payload"])}
        out = self._one(
            """
            INSERT INTO brain_observation_memory (
                observation_id, ticker, title, statement, kind, material, reason, fingerprint, payload, created_at
            ) VALUES (
                %(observation_id)s, %(ticker)s, %(title)s, %(statement)s, %(kind)s, %(material)s,
                %(reason)s, %(fingerprint)s, %(payload)s, %(created_at)s
            ) RETURNING *
            """,
            payload,
        )
        assert out is not None
        return out

    def list_observations(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            return [_copy(row) for row in self.observations.values() if row.get("ticker") == symbol]
        return self._execute(
            "SELECT * FROM brain_observation_memory WHERE ticker = %(ticker)s ORDER BY created_at DESC",
            {"ticker": symbol},
        )

    def upsert_market_attention(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "attention_id": row.get("attention_id") or new_id("batt"),
            "ticker": str(row["ticker"]).upper(),
            "name": row.get("name") or "",
            "statement": row.get("statement") or "",
            "object_id": row.get("object_id") or "",
            "related_objects": list(row.get("related_objects") or []),
            "source_kind": row.get("source_kind") or "news",
            "alignment": row.get("alignment") or "unknown",
            "evidence_ids": list(row.get("evidence_ids") or []),
            "reason": row.get("reason") or "",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            for existing in self.market_attentions.values():
                if existing.get("ticker") == stored["ticker"] and existing.get("name") == stored["name"]:
                    stored["attention_id"] = existing["attention_id"]
                    stored["created_at"] = existing.get("created_at") or stored["created_at"]
                    break
            self.market_attentions[stored["attention_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_market_attention (
                attention_id, ticker, name, statement, object_id, related_objects, source_kind,
                alignment, evidence_ids, reason, run_id, created_at, updated_at
            ) VALUES (
                %(attention_id)s, %(ticker)s, %(name)s, %(statement)s, %(object_id)s, %(related_objects)s,
                %(source_kind)s, %(alignment)s, %(evidence_ids)s, %(reason)s, %(run_id)s, %(created_at)s,
                %(updated_at)s
            )
            ON CONFLICT (ticker, name) DO UPDATE SET
                statement = EXCLUDED.statement,
                object_id = EXCLUDED.object_id,
                related_objects = EXCLUDED.related_objects,
                source_kind = EXCLUDED.source_kind,
                alignment = EXCLUDED.alignment,
                evidence_ids = EXCLUDED.evidence_ids,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_market_attentions(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            return [_copy(row) for row in self.market_attentions.values() if row.get("ticker") == symbol]
        return self._execute(
            "SELECT * FROM brain_market_attention WHERE ticker = %(ticker)s ORDER BY updated_at DESC",
            {"ticker": symbol},
        )

    def upsert_expectation(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "expectation_id": row.get("expectation_id") or new_id("bexpc"),
            "ticker": str(row["ticker"]).upper(),
            "name": row.get("name") or "",
            "subject": row.get("subject") or row.get("name") or "",
            "actual": row.get("actual"),
            "expected": row.get("expected"),
            "comparison": row.get("comparison") or "in_line",
            "trend": row.get("trend") or "unchanged",
            "confidence": row.get("confidence") or "medium",
            "supporting_evidence_ids": list(row.get("supporting_evidence_ids") or row.get("evidence_ids") or []),
            "last_material_change": row.get("last_material_change") or "",
            "reason": row.get("reason") or "",
            "source_kind": row.get("source_kind") or "news",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            for existing in self.expectations.values():
                if existing.get("ticker") == stored["ticker"] and existing.get("name") == stored["name"]:
                    stored["expectation_id"] = existing["expectation_id"]
                    stored["created_at"] = existing.get("created_at") or stored["created_at"]
                    stored["supporting_evidence_ids"] = list(
                        dict.fromkeys(list(existing.get("supporting_evidence_ids") or []) + stored["supporting_evidence_ids"])
                    )
                    break
            self.expectations[stored["expectation_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_expectations (
                expectation_id, ticker, name, subject, actual, expected, comparison, trend, confidence,
                supporting_evidence_ids, last_material_change, reason, source_kind, run_id, created_at, updated_at
            ) VALUES (
                %(expectation_id)s, %(ticker)s, %(name)s, %(subject)s, %(actual)s, %(expected)s, %(comparison)s,
                %(trend)s, %(confidence)s, %(supporting_evidence_ids)s, %(last_material_change)s, %(reason)s,
                %(source_kind)s, %(run_id)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (ticker, name) DO UPDATE SET
                actual = EXCLUDED.actual,
                expected = EXCLUDED.expected,
                comparison = EXCLUDED.comparison,
                trend = EXCLUDED.trend,
                confidence = EXCLUDED.confidence,
                supporting_evidence_ids = EXCLUDED.supporting_evidence_ids,
                last_material_change = EXCLUDED.last_material_change,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_expectations(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            return [_copy(row) for row in self.expectations.values() if row.get("ticker") == symbol]
        return self._execute(
            "SELECT * FROM brain_expectations WHERE ticker = %(ticker)s ORDER BY updated_at DESC",
            {"ticker": symbol},
        )

    def upsert_hypothesis(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "hypothesis_id": row.get("hypothesis_id") or new_id("bmdh"),
            "ticker": str(row["ticker"]).upper(),
            "canonical_key": row.get("canonical_key") or "",
            "kind": row.get("kind") or "other",
            "hypothesis": row.get("hypothesis") or "",
            "name": row.get("name") or row.get("canonical_key") or "",
            "confidence": row.get("confidence") or "low",
            "status": row.get("status") or "candidate",
            "supporting_observations": list(row.get("supporting_observations") or []),
            "counter_observations": list(row.get("counter_observations") or []),
            "related_expectation_id": row.get("related_expectation_id"),
            "related_attention_id": row.get("related_attention_id"),
            "related_causal_path": list(row.get("related_causal_path") or []),
            "source_kind": row.get("source_kind") or "news",
            "reason": row.get("reason") or "",
            "run_id": row.get("run_id"),
            "created_at": row.get("created_at") or _now(),
            "updated_at": row.get("updated_at") or _now(),
        }
        if not self._pg():
            for existing in self.hypotheses.values():
                if existing.get("ticker") == stored["ticker"] and existing.get("canonical_key") == stored["canonical_key"]:
                    stored["hypothesis_id"] = existing["hypothesis_id"]
                    stored["created_at"] = existing.get("created_at") or stored["created_at"]
                    stored["supporting_observations"] = list(
                        dict.fromkeys(list(existing.get("supporting_observations") or []) + stored["supporting_observations"])
                    )
                    stored["counter_observations"] = list(
                        dict.fromkeys(list(existing.get("counter_observations") or []) + stored["counter_observations"])
                    )
                    break
            self.hypotheses[stored["hypothesis_id"]] = stored
            return _copy(stored)
        out = self._one(
            """
            INSERT INTO brain_market_hypotheses (
                hypothesis_id, ticker, canonical_key, kind, hypothesis, name, confidence, status,
                supporting_observations, counter_observations, related_expectation_id, related_attention_id,
                related_causal_path, source_kind, reason, run_id, created_at, updated_at
            ) VALUES (
                %(hypothesis_id)s, %(ticker)s, %(canonical_key)s, %(kind)s, %(hypothesis)s, %(name)s,
                %(confidence)s, %(status)s, %(supporting_observations)s, %(counter_observations)s,
                %(related_expectation_id)s, %(related_attention_id)s, %(related_causal_path)s,
                %(source_kind)s, %(reason)s, %(run_id)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (ticker, canonical_key) DO UPDATE SET
                hypothesis = EXCLUDED.hypothesis,
                kind = EXCLUDED.kind,
                confidence = EXCLUDED.confidence,
                status = EXCLUDED.status,
                supporting_observations = EXCLUDED.supporting_observations,
                counter_observations = EXCLUDED.counter_observations,
                related_expectation_id = EXCLUDED.related_expectation_id,
                related_attention_id = EXCLUDED.related_attention_id,
                related_causal_path = EXCLUDED.related_causal_path,
                reason = EXCLUDED.reason,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            stored,
        )
        assert out is not None
        return out

    def list_hypotheses(self, ticker: str) -> list[dict[str, Any]]:
        symbol = ticker.upper()
        if not self._pg():
            return [_copy(row) for row in self.hypotheses.values() if row.get("ticker") == symbol]
        return self._execute(
            "SELECT * FROM brain_market_hypotheses WHERE ticker = %(ticker)s ORDER BY updated_at DESC",
            {"ticker": symbol},
        )
