"""PostgreSQL persistence for Brain research objects. Keep this out of queries.py."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from stock_pm.errors import DatabaseError

from .ids import new_id


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


class ResearchStore:
    def __init__(self, database: Any) -> None:
        self.database = database

    def _execute(self, query: str, params: dict[str, Any] | tuple | None = None) -> list[dict[str, Any]]:
        try:
            with self.database.pool.connection() as conn:
                result = conn.execute(query, params or {})
                if result.description is None:
                    return []
                return _rows(list(result.fetchall()))
        except Exception as exc:
            raise DatabaseError(f"research store failed: {exc}") from exc

    def _one(self, query: str, params: dict[str, Any] | tuple | None = None) -> dict[str, Any] | None:
        rows = self._execute(query, params)
        return rows[0] if rows else None

    def upsert_issuer(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **row,
            "aliases": list(row.get("aliases") or []),
            "missing_fields": _jsonb(row.get("missing_fields") or []),
            "updated_at": row.get("updated_at") or _now(),
        }
        stored = self._one(
            """
            INSERT INTO issuer_profiles (
                ticker, legal_name, cik, fiscal_year_end_month, sector, gics,
                primary_exchange, asset_class, aliases, missing_fields, source, updated_at
            )
            VALUES (
                %(ticker)s, %(legal_name)s, %(cik)s, %(fiscal_year_end_month)s,
                %(sector)s, %(gics)s, %(primary_exchange)s, %(asset_class)s,
                %(aliases)s, %(missing_fields)s, %(source)s, %(updated_at)s
            )
            ON CONFLICT (ticker) DO UPDATE SET
                legal_name = EXCLUDED.legal_name,
                cik = COALESCE(EXCLUDED.cik, issuer_profiles.cik),
                fiscal_year_end_month = COALESCE(EXCLUDED.fiscal_year_end_month, issuer_profiles.fiscal_year_end_month),
                sector = COALESCE(EXCLUDED.sector, issuer_profiles.sector),
                gics = COALESCE(EXCLUDED.gics, issuer_profiles.gics),
                primary_exchange = CASE WHEN EXCLUDED.primary_exchange = '' THEN issuer_profiles.primary_exchange ELSE EXCLUDED.primary_exchange END,
                asset_class = EXCLUDED.asset_class,
                aliases = EXCLUDED.aliases,
                missing_fields = EXCLUDED.missing_fields,
                source = EXCLUDED.source,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_issuer(self, ticker: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM issuer_profiles WHERE ticker = %(ticker)s", {"ticker": ticker.upper()})

    def insert_workflow_run(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("wrun"),
            "ticker": row["ticker"].upper(),
            "workflow_name": row.get("workflow_name") or "new_ticker_research",
            "trigger": row.get("trigger") or "api",
            "template_id": row.get("template_id"),
            "status": row.get("status") or "running",
            "config_json": _jsonb(row.get("config_json") or {}),
            "item_counts": _jsonb(row.get("item_counts") or {}),
            "error": row.get("error"),
            "started_at": row.get("started_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        stored = self._one(
            """
            INSERT INTO research_workflow_runs (
                id, ticker, workflow_name, trigger, template_id, status,
                config_json, item_counts, error, started_at, completed_at
            )
            VALUES (
                %(id)s, %(ticker)s, %(workflow_name)s, %(trigger)s, %(template_id)s,
                %(status)s, %(config_json)s, %(item_counts)s, %(error)s,
                %(started_at)s, %(completed_at)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM research_workflow_runs WHERE id = %(id)s", {"id": run_id})

    def list_workflow_runs(self, ticker: str) -> list[dict[str, Any]]:
        return self._execute(
            """
            SELECT * FROM research_workflow_runs
            WHERE ticker = %(ticker)s
            ORDER BY started_at DESC
            """,
            {"ticker": ticker.upper()},
        )

    def complete_workflow_run(self, run_id: str, *, status: str, item_counts: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        stored = self._one(
            """
            UPDATE research_workflow_runs
            SET status = %(status)s,
                item_counts = %(item_counts)s,
                error = %(error)s,
                completed_at = %(completed_at)s
            WHERE id = %(id)s
            RETURNING *
            """,
            {
                "id": run_id,
                "status": status,
                "item_counts": _jsonb(item_counts or {}),
                "error": error,
                "completed_at": _now(),
            },
        )
        if stored is None:
            raise DatabaseError(f"workflow run not found: {run_id}")
        return stored

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("rtask"),
            "ticker": row["ticker"].upper(),
            "workflow_run_id": row.get("workflow_run_id"),
            "parent_task_id": row.get("parent_task_id"),
            "root_task_id": row.get("root_task_id"),
            "depth": int(row.get("depth") or 0),
            "task_type": row["task_type"],
            "title": row["title"],
            "description": row.get("description") or "",
            "source_reason": row.get("source_reason") or "",
            "required_data": _jsonb(list(row.get("required_data") or [])),
            "assigned_agents": list(row.get("assigned_agents") or []),
            "priority": int(row.get("priority") or 50),
            "status": row.get("status") or "pending",
            "created_by": row.get("created_by") or "system",
            "created_at": row.get("created_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        stored = self._one(
            """
            INSERT INTO research_tasks (
                id, ticker, workflow_run_id, parent_task_id, root_task_id, depth,
                task_type, title, description, source_reason, required_data,
                assigned_agents, priority, status, created_by, created_at, completed_at
            )
            VALUES (
                %(id)s, %(ticker)s, %(workflow_run_id)s, %(parent_task_id)s, %(root_task_id)s,
                %(depth)s, %(task_type)s, %(title)s, %(description)s, %(source_reason)s,
                %(required_data)s, %(assigned_agents)s, %(priority)s, %(status)s,
                %(created_by)s, %(created_at)s, %(completed_at)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        if not stored.get("root_task_id"):
            stored = self._one(
                "UPDATE research_tasks SET root_task_id = id WHERE id = %(id)s RETURNING *",
                {"id": stored["id"]},
            )
            assert stored is not None
        return stored

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM research_tasks WHERE id = %(id)s", {"id": task_id})

    def list_tasks(self, ticker: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
        if workflow_run_id:
            return self._execute(
                """
                SELECT * FROM research_tasks
                WHERE ticker = %(ticker)s AND workflow_run_id = %(workflow_run_id)s
                ORDER BY depth, priority, created_at
                """,
                {"ticker": ticker.upper(), "workflow_run_id": workflow_run_id},
            )
        return self._execute(
            """
            SELECT * FROM research_tasks
            WHERE ticker = %(ticker)s
            ORDER BY created_at DESC
            """,
            {"ticker": ticker.upper()},
        )

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"status", "completed_at", "title", "description"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            current = self.get_task(task_id)
            if current is None:
                raise DatabaseError(f"task not found: {task_id}")
            return current
        assignments = ", ".join(f"{key} = %({key})s" for key in updates)
        stored = self._one(
            f"UPDATE research_tasks SET {assignments} WHERE id = %(id)s RETURNING *",
            {"id": task_id, **updates},
        )
        if stored is None:
            raise DatabaseError(f"task not found: {task_id}")
        return stored

    def next_pending_task(self, ticker: str, workflow_run_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM research_tasks
            WHERE ticker = %(ticker)s
              AND workflow_run_id = %(workflow_run_id)s
              AND status = 'pending'
            ORDER BY priority ASC, created_at ASC
            LIMIT 1
            """,
            {"ticker": ticker.upper(), "workflow_run_id": workflow_run_id},
        )

    def insert_agent_run(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("arun"),
            "workflow_run_id": row.get("workflow_run_id"),
            "task_id": row.get("task_id"),
            "ticker": row["ticker"].upper(),
            "agent_name": row["agent_name"],
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "input_hash": row.get("input_hash"),
            "output_json": _jsonb(row.get("output_json") or {}),
            "confidence": row.get("confidence"),
            "status": row.get("status") or "running",
            "error": row.get("error"),
            "started_at": row.get("started_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        stored = self._one(
            """
            INSERT INTO research_agent_runs (
                id, workflow_run_id, task_id, ticker, agent_name, model, prompt_version,
                input_hash, output_json, confidence, status, error, started_at, completed_at
            )
            VALUES (
                %(id)s, %(workflow_run_id)s, %(task_id)s, %(ticker)s, %(agent_name)s,
                %(model)s, %(prompt_version)s, %(input_hash)s, %(output_json)s,
                %(confidence)s, %(status)s, %(error)s, %(started_at)s, %(completed_at)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def complete_agent_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        payload = {
            "id": run_id,
            "status": fields.get("status") or "success",
            "output_json": _jsonb(fields.get("output_json") or {}),
            "confidence": fields.get("confidence"),
            "error": fields.get("error"),
            "completed_at": fields.get("completed_at") or _now(),
        }
        stored = self._one(
            """
            UPDATE research_agent_runs
            SET status = %(status)s,
                output_json = %(output_json)s,
                confidence = %(confidence)s,
                error = %(error)s,
                completed_at = %(completed_at)s
            WHERE id = %(id)s
            RETURNING *
            """,
            payload,
        )
        if stored is None:
            raise DatabaseError(f"agent run not found: {run_id}")
        return stored

    def list_agent_runs(self, ticker: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
        if workflow_run_id:
            return self._execute(
                """
                SELECT * FROM research_agent_runs
                WHERE ticker = %(ticker)s AND workflow_run_id = %(workflow_run_id)s
                ORDER BY started_at
                """,
                {"ticker": ticker.upper(), "workflow_run_id": workflow_run_id},
            )
        return self._execute(
            """
            SELECT * FROM research_agent_runs
            WHERE ticker = %(ticker)s
            ORDER BY started_at DESC
            """,
            {"ticker": ticker.upper()},
        )

    def insert_evidence(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("rev"),
            "ticker": row["ticker"].upper(),
            "evidence_type": row["evidence_type"],
            "fact": row["fact"],
            "source": row["source"],
            "source_url": row.get("source_url"),
            "source_time": row["source_time"],
            "retrieved_at": row["retrieved_at"],
            "confidence": row.get("confidence"),
            "importance": row.get("importance") or "medium",
            "direction": row.get("direction") or "neutral",
            "raw_reference": _jsonb(row.get("raw_reference") or {}),
            "produced_by": row.get("produced_by") or "human_api",
            "task_id": row.get("task_id"),
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
        }
        stored = self._one(
            """
            INSERT INTO research_evidence (
                id, ticker, evidence_type, fact, source, source_url, source_time,
                retrieved_at, confidence, importance, direction, raw_reference,
                produced_by, task_id, workflow_run_id, agent_run_id, model, prompt_version
            )
            VALUES (
                %(id)s, %(ticker)s, %(evidence_type)s, %(fact)s, %(source)s, %(source_url)s,
                %(source_time)s, %(retrieved_at)s, %(confidence)s, %(importance)s,
                %(direction)s, %(raw_reference)s, %(produced_by)s, %(task_id)s,
                %(workflow_run_id)s, %(agent_run_id)s, %(model)s, %(prompt_version)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM research_evidence WHERE id = %(id)s", {"id": evidence_id})

    def list_evidence(self, ticker: str) -> list[dict[str, Any]]:
        return self._execute(
            """
            SELECT * FROM research_evidence
            WHERE ticker = %(ticker)s
            ORDER BY source_time DESC, created_at DESC
            """,
            {"ticker": ticker.upper()},
        )

    def insert_assumption(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("rasm"),
            "ticker": row["ticker"].upper(),
            "category": row.get("category") or "other",
            "statement": row["statement"],
            "status": row.get("status") or "unverified",
            "importance": row.get("importance") or "medium",
            "thesis_role": row.get("thesis_role") or "supporting",
            "confidence": row.get("confidence"),
            "next_verification": row.get("next_verification"),
            "proposed_by": row.get("proposed_by") or "human_api",
            "status_updated_by": row.get("status_updated_by"),
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "updated_at": _now(),
        }
        stored = self._one(
            """
            INSERT INTO research_assumptions (
                id, ticker, category, statement, status, importance, thesis_role,
                confidence, next_verification, proposed_by, status_updated_by,
                workflow_run_id, agent_run_id, model, prompt_version, updated_at
            )
            VALUES (
                %(id)s, %(ticker)s, %(category)s, %(statement)s, %(status)s,
                %(importance)s, %(thesis_role)s, %(confidence)s, %(next_verification)s,
                %(proposed_by)s, %(status_updated_by)s, %(workflow_run_id)s,
                %(agent_run_id)s, %(model)s, %(prompt_version)s, %(updated_at)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_assumption(self, assumption_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM research_assumptions WHERE id = %(id)s", {"id": assumption_id})

    def list_assumptions(self, ticker: str) -> list[dict[str, Any]]:
        return self._execute(
            """
            SELECT * FROM research_assumptions
            WHERE ticker = %(ticker)s
            ORDER BY
                CASE thesis_role WHEN 'core' THEN 0 WHEN 'risk' THEN 1 ELSE 2 END,
                created_at
            """,
            {"ticker": ticker.upper()},
        )

    def update_assumption(self, assumption_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "importance",
            "thesis_role",
            "confidence",
            "next_verification",
            "status_updated_by",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        updates["updated_at"] = _now()
        assignments = ", ".join(f"{key} = %({key})s" for key in updates)
        stored = self._one(
            f"UPDATE research_assumptions SET {assignments} WHERE id = %(id)s RETURNING *",
            {"id": assumption_id, **updates},
        )
        if stored is None:
            raise DatabaseError(f"assumption not found: {assumption_id}")
        return stored

    def insert_link(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "assumption_id": row["assumption_id"],
            "evidence_id": row["evidence_id"],
            "direction": row["direction"],
            "linked_by": row.get("linked_by") or "system",
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
        }
        stored = self._one(
            """
            INSERT INTO assumption_evidence_links (
                assumption_id, evidence_id, direction, linked_by, workflow_run_id, agent_run_id
            )
            VALUES (
                %(assumption_id)s, %(evidence_id)s, %(direction)s, %(linked_by)s,
                %(workflow_run_id)s, %(agent_run_id)s
            )
            ON CONFLICT (assumption_id, evidence_id, direction) DO UPDATE SET
                linked_by = EXCLUDED.linked_by
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def list_links(
        self,
        *,
        ticker: str | None = None,
        assumption_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if assumption_id:
            return self._execute(
                """
                SELECT links.*, assumptions.ticker AS assumption_ticker, evidence.ticker AS evidence_ticker
                FROM assumption_evidence_links links
                JOIN research_assumptions assumptions ON assumptions.id = links.assumption_id
                JOIN research_evidence evidence ON evidence.id = links.evidence_id
                WHERE links.assumption_id = %(assumption_id)s
                ORDER BY links.linked_at
                """,
                {"assumption_id": assumption_id},
            )
        if evidence_id:
            return self._execute(
                """
                SELECT links.*, assumptions.ticker AS assumption_ticker, evidence.ticker AS evidence_ticker
                FROM assumption_evidence_links links
                JOIN research_assumptions assumptions ON assumptions.id = links.assumption_id
                JOIN research_evidence evidence ON evidence.id = links.evidence_id
                WHERE links.evidence_id = %(evidence_id)s
                ORDER BY links.linked_at
                """,
                {"evidence_id": evidence_id},
            )
        return self._execute(
            """
            SELECT links.*, assumptions.ticker AS assumption_ticker, evidence.ticker AS evidence_ticker
            FROM assumption_evidence_links links
            JOIN research_assumptions assumptions ON assumptions.id = links.assumption_id
            JOIN research_evidence evidence ON evidence.id = links.evidence_id
            WHERE assumptions.ticker = %(ticker)s
            ORDER BY links.linked_at
            """,
            {"ticker": (ticker or "").upper()},
        )

    def insert_thesis(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("ith"),
            "ticker": row["ticker"].upper(),
            "version": int(row["version"]),
            "short_term_view": row.get("short_term_view") or "",
            "mid_term_view": row.get("mid_term_view") or "",
            "long_term_view": row.get("long_term_view") or "",
            "core_thesis": row["core_thesis"],
            "key_assumption_ids": list(row.get("key_assumption_ids") or []),
            "key_risks": _jsonb(row.get("key_risks") or []),
            "invalidation_conditions": _jsonb(row.get("invalidation_conditions") or []),
            "monitoring_items": _jsonb(row.get("monitoring_items") or []),
            "confidence": row.get("confidence"),
            "valuation_id": row.get("valuation_id"),
            "change_summary": row.get("change_summary"),
            "actor": row["actor"],
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
        }
        stored = self._one(
            """
            INSERT INTO investment_theses (
                id, ticker, version, short_term_view, mid_term_view, long_term_view,
                core_thesis, key_assumption_ids, key_risks, invalidation_conditions,
                monitoring_items, confidence, valuation_id, change_summary, actor,
                workflow_run_id, agent_run_id, model, prompt_version
            )
            VALUES (
                %(id)s, %(ticker)s, %(version)s, %(short_term_view)s, %(mid_term_view)s,
                %(long_term_view)s, %(core_thesis)s, %(key_assumption_ids)s, %(key_risks)s,
                %(invalidation_conditions)s, %(monitoring_items)s, %(confidence)s,
                %(valuation_id)s, %(change_summary)s, %(actor)s, %(workflow_run_id)s,
                %(agent_run_id)s, %(model)s, %(prompt_version)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def next_thesis_version(self, ticker: str) -> int:
        row = self._one(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM investment_theses WHERE ticker = %(ticker)s",
            {"ticker": ticker.upper()},
        )
        return int((row or {}).get("max_version") or 0) + 1

    def get_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM investment_theses WHERE id = %(id)s", {"id": thesis_id})

    def get_latest_thesis(self, ticker: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM investment_theses
            WHERE ticker = %(ticker)s
            ORDER BY version DESC
            LIMIT 1
            """,
            {"ticker": ticker.upper()},
        )

    def list_theses(self, ticker: str) -> list[dict[str, Any]]:
        return self._execute(
            """
            SELECT * FROM investment_theses
            WHERE ticker = %(ticker)s
            ORDER BY version
            """,
            {"ticker": ticker.upper()},
        )

    def bind_thesis_valuation(self, thesis_id: str, valuation_id: str) -> dict[str, Any]:
        stored = self._one(
            """
            UPDATE investment_theses
            SET valuation_id = %(valuation_id)s
            WHERE id = %(id)s
            RETURNING *
            """,
            {"id": thesis_id, "valuation_id": valuation_id},
        )
        if stored is None:
            raise DatabaseError(f"thesis not found: {thesis_id}")
        return stored

    def insert_valuation(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "id": row.get("id") or new_id("val"),
            "ticker": row["ticker"].upper(),
            "thesis_id": row.get("thesis_id"),
            "thesis_version": row.get("thesis_version"),
            "horizon": row.get("horizon") or "2y",
            "bear_case": _jsonb(row.get("bear_case") or {}),
            "base_case": _jsonb(row.get("base_case") or {}),
            "bull_case": _jsonb(row.get("bull_case") or {}),
            "spot_price": row.get("spot_price"),
            "actor": row.get("actor") or "pm_judge",
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
        }
        stored = self._one(
            """
            INSERT INTO valuations (
                id, ticker, thesis_id, thesis_version, horizon, bear_case, base_case,
                bull_case, spot_price, actor, workflow_run_id, agent_run_id, model, prompt_version
            )
            VALUES (
                %(id)s, %(ticker)s, %(thesis_id)s, %(thesis_version)s, %(horizon)s,
                %(bear_case)s, %(base_case)s, %(bull_case)s, %(spot_price)s, %(actor)s,
                %(workflow_run_id)s, %(agent_run_id)s, %(model)s, %(prompt_version)s
            )
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_valuation(self, valuation_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM valuations WHERE id = %(id)s", {"id": valuation_id})

    def get_valuation_for_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM valuations
            WHERE thesis_id = %(thesis_id)s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"thesis_id": thesis_id},
        )

    def upsert_pack(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "ticker": row["ticker"].upper(),
            "template_id": row.get("template_id") or "generic_company",
            "company_profile": _jsonb(row.get("company_profile") or {}),
            "earnings_history": _jsonb(row.get("earnings_history") or []),
            "guidance_history": _jsonb(row.get("guidance_history") or []),
            "price_reaction_history": _jsonb(row.get("price_reaction_history") or []),
            "industry_context": _jsonb(row.get("industry_context") or {}),
            "competitive_context": _jsonb(row.get("competitive_context") or {}),
            "major_events": _jsonb(row.get("major_events") or []),
            "missing_fields": _jsonb(row.get("missing_fields") or []),
            "source_refs": _jsonb(row.get("source_refs") or {}),
            "workflow_run_id": row.get("workflow_run_id"),
            "updated_at": _now(),
        }
        stored = self._one(
            """
            INSERT INTO research_packs (
                ticker, template_id, company_profile, earnings_history, guidance_history,
                price_reaction_history, industry_context, competitive_context, major_events,
                missing_fields, source_refs, workflow_run_id, updated_at
            )
            VALUES (
                %(ticker)s, %(template_id)s, %(company_profile)s, %(earnings_history)s,
                %(guidance_history)s, %(price_reaction_history)s, %(industry_context)s,
                %(competitive_context)s, %(major_events)s, %(missing_fields)s,
                %(source_refs)s, %(workflow_run_id)s, %(updated_at)s
            )
            ON CONFLICT (ticker) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                company_profile = EXCLUDED.company_profile,
                earnings_history = EXCLUDED.earnings_history,
                guidance_history = EXCLUDED.guidance_history,
                price_reaction_history = EXCLUDED.price_reaction_history,
                industry_context = EXCLUDED.industry_context,
                competitive_context = EXCLUDED.competitive_context,
                major_events = EXCLUDED.major_events,
                missing_fields = EXCLUDED.missing_fields,
                source_refs = EXCLUDED.source_refs,
                workflow_run_id = EXCLUDED.workflow_run_id,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            payload,
        )
        assert stored is not None
        return stored

    def get_pack(self, ticker: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM research_packs WHERE ticker = %(ticker)s", {"ticker": ticker.upper()})
