"""In-memory research store for invariant and workflow tests (no Postgres)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from stock_pm.errors import DatabaseError

from .ids import new_id


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _copy(row: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(row)


class InMemoryResearchStore:
    def __init__(self) -> None:
        self.issuers: dict[str, dict[str, Any]] = {}
        self.workflow_runs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.agent_runs: dict[str, dict[str, Any]] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.assumptions: dict[str, dict[str, Any]] = {}
        self.links: list[dict[str, Any]] = []
        self.theses: dict[str, dict[str, Any]] = {}
        self.valuations: dict[str, dict[str, Any]] = {}
        self.packs: dict[str, dict[str, Any]] = {}
        self.source_documents: dict[str, dict[str, Any]] = {}
        self.backfills: dict[str, dict[str, Any]] = {}
        self.assumption_proposals: dict[str, dict[str, Any]] = {}
        self.pm_rulings: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.raw_earnings: dict[str, list[dict[str, Any]]] = {}
        self.raw_fundamentals: dict[str, Any] = {}
        self.raw_news: dict[str, list[dict[str, Any]]] = {}
        self.raw_bars: dict[str, list[dict[str, Any]]] = {}
        self.raw_events: dict[str, list[dict[str, Any]]] = {}

    def upsert_issuer(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = row["ticker"].upper()
        current = dict(self.issuers.get(ticker) or {})
        for key, value in row.items():
            if key == "ticker":
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                if current.get(key) not in (None, ""):
                    continue
            if key == "aliases" and not value and current.get("aliases"):
                continue
            current[key] = value
        current["ticker"] = ticker
        current["updated_at"] = _now()
        self.issuers[ticker] = current
        return _copy(current)

    def get_issuer(self, ticker: str) -> dict[str, Any] | None:
        row = self.issuers.get(ticker.upper())
        return _copy(row) if row else None

    def insert_workflow_run(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("wrun"),
            "ticker": row["ticker"].upper(),
            "workflow_name": row.get("workflow_name") or "new_ticker_research",
            "trigger": row.get("trigger") or "api",
            "template_id": row.get("template_id"),
            "status": row.get("status") or "running",
            "config_json": dict(row.get("config_json") or {}),
            "item_counts": dict(row.get("item_counts") or {}),
            "error": row.get("error"),
            "started_at": row.get("started_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        self.workflow_runs[stored["id"]] = stored
        return _copy(stored)

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.workflow_runs.get(run_id)
        return _copy(row) if row else None

    def list_workflow_runs(self, ticker: str) -> list[dict[str, Any]]:
        rows = [row for row in self.workflow_runs.values() if row["ticker"] == ticker.upper()]
        return [_copy(row) for row in sorted(rows, key=lambda item: str(item.get("started_at")), reverse=True)]

    def complete_workflow_run(self, run_id: str, *, status: str, item_counts: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
        row = self.workflow_runs.get(run_id)
        if row is None:
            raise DatabaseError(f"workflow run not found: {run_id}")
        row["status"] = status
        row["item_counts"] = dict(item_counts or {})
        row["error"] = error
        row["completed_at"] = _now()
        return _copy(row)

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
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
            "source_type": row.get("source_type") or "agent_followup",
            "required_data": list(row.get("required_data") or []),
            "assigned_agents": list(row.get("assigned_agents") or []),
            "priority": int(row.get("priority") or 50),
            "status": row.get("status") or "pending",
            "created_by": row.get("created_by") or "system",
            "created_at": row.get("created_at") or _now(),
            "completed_at": row.get("completed_at"),
        }
        stored["root_task_id"] = stored["root_task_id"] or stored["id"]
        self.tasks[stored["id"]] = stored
        return _copy(stored)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.tasks.get(task_id)
        return _copy(row) if row else None

    def list_tasks(self, ticker: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.tasks.values() if row["ticker"] == ticker.upper()]
        if workflow_run_id:
            rows = [row for row in rows if row.get("workflow_run_id") == workflow_run_id]
        return [_copy(row) for row in rows]

    def update_task(self, task_id: str, **fields: Any) -> dict[str, Any]:
        row = self.tasks.get(task_id)
        if row is None:
            raise DatabaseError(f"task not found: {task_id}")
        row.update({key: value for key, value in fields.items() if value is not None or key == "completed_at"})
        return _copy(row)

    def next_pending_task(self, ticker: str, workflow_run_id: str) -> dict[str, Any] | None:
        pending = [
            row
            for row in self.tasks.values()
            if row["ticker"] == ticker.upper()
            and row.get("workflow_run_id") == workflow_run_id
            and row.get("status") == "pending"
        ]
        pending.sort(key=lambda item: (int(item.get("priority") or 50), str(item.get("created_at"))))
        return _copy(pending[0]) if pending else None

    def insert_agent_run(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("arun"),
            "workflow_run_id": row.get("workflow_run_id"),
            "task_id": row.get("task_id"),
            "ticker": row["ticker"].upper(),
            "agent_name": row["agent_name"],
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "input_hash": row.get("input_hash"),
            "output_json": dict(row.get("output_json") or {}),
            "confidence": row.get("confidence"),
            "status": row.get("status") or "running",
            "error": row.get("error"),
            "started_at": row.get("started_at") or _now(),
            "completed_at": row.get("completed_at"),
            "llm_called": bool(row.get("llm_called")),
            "llm_status": row.get("llm_status"),
            "llm_provider": row.get("llm_provider") or row.get("provider"),
            "prompt_hash": row.get("prompt_hash"),
            "latency_ms": row.get("latency_ms"),
            "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"),
            "total_tokens": row.get("total_tokens"),
            "fallback_used": bool(row.get("fallback_used")),
        }
        self.agent_runs[stored["id"]] = stored
        return _copy(stored)

    def complete_agent_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        row = self.agent_runs.get(run_id)
        if row is None:
            raise DatabaseError(f"agent run not found: {run_id}")
        row["status"] = fields.get("status") or "success"
        row["output_json"] = dict(fields.get("output_json") or {})
        row["confidence"] = fields.get("confidence")
        row["error"] = fields.get("error")
        row["completed_at"] = fields.get("completed_at") or _now()
        if fields.get("model"):
            row["model"] = fields.get("model")
        if fields.get("prompt_version"):
            row["prompt_version"] = fields.get("prompt_version")
        for key in (
            "llm_called",
            "llm_status",
            "llm_provider",
            "prompt_hash",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "fallback_used",
        ):
            if key in fields and fields.get(key) is not None:
                row[key] = fields.get(key)
        return _copy(row)

    def list_agent_runs(self, ticker: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.agent_runs.values() if row["ticker"] == ticker.upper()]
        if workflow_run_id:
            rows = [row for row in rows if row.get("workflow_run_id") == workflow_run_id]
        return [_copy(row) for row in rows]

    def insert_evidence(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
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
            "raw_reference": dict(row.get("raw_reference") or {}),
            "excerpt": str(row.get("excerpt") or row.get("fact") or ""),
            "source_type": str(row.get("source_type") or ""),
            "produced_by": row.get("produced_by") or "human_api",
            "task_id": row.get("task_id"),
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "source_quality": row.get("source_quality") or "secondary",
            "independence_key": str(row.get("independence_key") or ""),
            "created_at": _now(),
        }
        self.evidence[stored["id"]] = stored
        return _copy(stored)

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.evidence.get(evidence_id)
        return _copy(row) if row else None

    def list_evidence(self, ticker: str) -> list[dict[str, Any]]:
        return [_copy(row) for row in self.evidence.values() if row["ticker"] == ticker.upper()]

    def insert_assumption(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
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
            "source_type": row.get("source_type") or "template_seed",
            "invalidation_condition": row.get("invalidation_condition"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.assumptions[stored["id"]] = stored
        return _copy(stored)

    def get_assumption(self, assumption_id: str) -> dict[str, Any] | None:
        row = self.assumptions.get(assumption_id)
        return _copy(row) if row else None

    def list_assumptions(self, ticker: str) -> list[dict[str, Any]]:
        return [_copy(row) for row in self.assumptions.values() if row["ticker"] == ticker.upper()]

    def update_assumption(self, assumption_id: str, **fields: Any) -> dict[str, Any]:
        row = self.assumptions.get(assumption_id)
        if row is None:
            raise DatabaseError(f"assumption not found: {assumption_id}")
        row.update(fields)
        row["updated_at"] = _now()
        return _copy(row)

    def insert_link(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "assumption_id": row["assumption_id"],
            "evidence_id": row["evidence_id"],
            "direction": row["direction"],
            "strength": row.get("strength") or "moderate",
            "relevance": row.get("relevance") or "indirect",
            "reason": row.get("reason"),
            "linked_by": row.get("linked_by") or "system",
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "linked_at": _now(),
        }
        key = (stored["assumption_id"], stored["evidence_id"], stored["direction"])
        self.links = [item for item in self.links if (item["assumption_id"], item["evidence_id"], item["direction"]) != key]
        self.links.append(stored)
        return _copy(stored)

    def list_links(
        self,
        *,
        ticker: str | None = None,
        assumption_id: str | None = None,
        evidence_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = []
        for item in self.links:
            assumption = self.assumptions.get(item["assumption_id"]) or {}
            evidence = self.evidence.get(item["evidence_id"]) or {}
            packed = {
                **item,
                "assumption_ticker": assumption.get("ticker"),
                "evidence_ticker": evidence.get("ticker"),
            }
            if assumption_id and item["assumption_id"] != assumption_id:
                continue
            if evidence_id and item["evidence_id"] != evidence_id:
                continue
            if ticker and assumption.get("ticker") != ticker.upper():
                continue
            rows.append(packed)
        return [_copy(row) for row in rows]

    def insert_thesis(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("ith"),
            "ticker": row["ticker"].upper(),
            "version": int(row["version"]),
            "short_term_view": row.get("short_term_view") or "",
            "mid_term_view": row.get("mid_term_view") or "",
            "long_term_view": row.get("long_term_view") or "",
            "core_thesis": row["core_thesis"],
            "key_assumption_ids": list(row.get("key_assumption_ids") or []),
            "core_assumption_ids": list(row.get("core_assumption_ids") or row.get("key_assumption_ids") or []),
            "supporting_assumption_ids": list(row.get("supporting_assumption_ids") or []),
            "key_risks": list(row.get("key_risks") or []),
            "key_catalysts": list(row.get("key_catalysts") or []),
            "invalidation_conditions": list(row.get("invalidation_conditions") or []),
            "monitoring_items": list(row.get("monitoring_items") or []),
            "confidence": row.get("confidence"),
            "research_quality": dict(row.get("research_quality") or {}),
            "market_reaction": row.get("market_reaction") or "",
            "thesis_diff": dict(row.get("thesis_diff") or {}),
            "valuation_id": row.get("valuation_id"),
            "change_summary": row.get("change_summary"),
            "actor": row["actor"],
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "snapshot_id": row.get("snapshot_id"),
            "created_at": _now(),
        }
        self.theses[stored["id"]] = stored
        return _copy(stored)

    def next_thesis_version(self, ticker: str) -> int:
        versions = [int(row["version"]) for row in self.theses.values() if row["ticker"] == ticker.upper()]
        return (max(versions) if versions else 0) + 1

    def get_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        row = self.theses.get(thesis_id)
        return _copy(row) if row else None

    def get_latest_thesis(self, ticker: str) -> dict[str, Any] | None:
        rows = [row for row in self.theses.values() if row["ticker"] == ticker.upper()]
        if not rows:
            return None
        rows.sort(key=lambda item: int(item["version"]))
        return _copy(rows[-1])

    def list_theses(self, ticker: str) -> list[dict[str, Any]]:
        rows = [row for row in self.theses.values() if row["ticker"] == ticker.upper()]
        rows.sort(key=lambda item: int(item["version"]))
        return [_copy(row) for row in rows]

    def bind_thesis_valuation(self, thesis_id: str, valuation_id: str) -> dict[str, Any]:
        row = self.theses.get(thesis_id)
        if row is None:
            raise DatabaseError(f"thesis not found: {thesis_id}")
        row["valuation_id"] = valuation_id
        return _copy(row)

    def insert_valuation(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("val"),
            "ticker": row["ticker"].upper(),
            "thesis_id": row.get("thesis_id"),
            "thesis_version": row.get("thesis_version"),
            "horizon": row.get("horizon") or "2y",
            "bear_case": dict(row.get("bear_case") or {}),
            "base_case": dict(row.get("base_case") or {}),
            "bull_case": dict(row.get("bull_case") or {}),
            "spot_price": row.get("spot_price"),
            "actor": row.get("actor") or "pm_judge",
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "calibration_json": dict(row.get("calibration_json") or {}),
            "snapshot_id": row.get("snapshot_id"),
            "valuation_method_version": row.get("valuation_method_version"),
            "created_at": _now(),
        }
        self.valuations[stored["id"]] = stored
        return _copy(stored)

    def get_valuation(self, valuation_id: str) -> dict[str, Any] | None:
        row = self.valuations.get(valuation_id)
        return _copy(row) if row else None

    def get_valuation_for_thesis(self, thesis_id: str) -> dict[str, Any] | None:
        rows = [row for row in self.valuations.values() if row.get("thesis_id") == thesis_id]
        return _copy(rows[-1]) if rows else None

    def list_valuations(self, ticker: str) -> list[dict[str, Any]]:
        rows = [row for row in self.valuations.values() if row["ticker"] == ticker.upper()]
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return [_copy(row) for row in rows]

    def update_thesis_meta(self, thesis_id: str, **fields: Any) -> dict[str, Any]:
        row = self.theses.get(thesis_id)
        if row is None:
            raise DatabaseError(f"thesis not found: {thesis_id}")
        allowed = {"thesis_diff", "research_quality", "market_reaction", "change_summary", "valuation_id", "snapshot_id"}
        for key, value in fields.items():
            if key in allowed:
                row[key] = value
        return _copy(row)

    def insert_pm_ruling(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("rpm"),
            "ticker": str(row["ticker"]).upper(),
            "thesis_id": row.get("thesis_id"),
            "workflow_run_id": row.get("workflow_run_id"),
            "assumption_id": row["assumption_id"],
            "final_status": row["final_status"],
            "final_confidence": row.get("final_confidence"),
            "thesis_role": row.get("thesis_role") or "supporting",
            "reasoning": row["reasoning"],
            "key_supporting_evidence_ids": list(row.get("key_supporting_evidence_ids") or []),
            "key_opposing_evidence_ids": list(row.get("key_opposing_evidence_ids") or []),
            "unresolved_gaps": list(row.get("unresolved_gaps") or []),
            "invalidation_condition": row.get("invalidation_condition"),
            "next_verification": row.get("next_verification"),
            "engine_proposed_status": row.get("engine_proposed_status"),
            "snapshot_id": row.get("snapshot_id"),
            "created_at": _now(),
        }
        self.pm_rulings[stored["id"]] = stored
        return _copy(stored)

    def list_pm_rulings(self, ticker: str, thesis_id: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.pm_rulings.values() if row["ticker"] == ticker.upper()]
        if thesis_id:
            rows = [row for row in rows if row.get("thesis_id") == thesis_id]
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return [_copy(row) for row in rows]

    def upsert_pack(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = row["ticker"].upper()
        profile = dict(row.get("company_profile") or {})
        official = list(row.get("official_documents") or profile.get("official_documents") or [])
        if official:
            profile["official_documents"] = official
        existing = self.packs.get(ticker) or {}
        pack_version = int(row.get("pack_version") or (int(existing.get("pack_version") or 0) + 1) or 1)
        pack_id = row.get("pack_id") or f"pack_{ticker.lower()}_v{pack_version}"
        stored = {
            "ticker": ticker,
            "pack_id": pack_id,
            "pack_version": pack_version,
            "template_id": row.get("template_id") or "generic_company",
            "company_profile": profile,
            "earnings_history": list(row.get("earnings_history") or []),
            "guidance_history": list(row.get("guidance_history") or []),
            "price_reaction_history": list(row.get("price_reaction_history") or []),
            "industry_context": dict(row.get("industry_context") or {}),
            "competitive_context": dict(row.get("competitive_context") or {}),
            "major_events": list(row.get("major_events") or []),
            "official_documents": official,
            "missing_fields": list(row.get("missing_fields") or []),
            "source_refs": dict(row.get("source_refs") or {}),
            "workflow_run_id": row.get("workflow_run_id"),
            "is_fixture": bool(row.get("is_fixture")),
            "source": row.get("source") or ("fixture" if row.get("is_fixture") else "production"),
            "updated_at": _now(),
        }
        self.packs[ticker] = stored
        return _copy(stored)

    def get_pack(self, ticker: str) -> dict[str, Any] | None:
        row = self.packs.get(ticker.upper())
        return _copy(row) if row else None

    def upsert_source_document(self, row: dict[str, Any]) -> dict[str, Any]:
        ticker = str(row["ticker"]).upper()
        source_key = str(row.get("source_key") or row.get("url") or row.get("title") or row["doc_type"])[:500]
        found = None
        for item in self.source_documents.values():
            if item["ticker"] == ticker and item["doc_type"] == row["doc_type"] and item["source_key"] == source_key:
                found = item
                break
        stored = found or {}
        stored.update(
            {
                "id": stored.get("id") or row.get("id") or new_id("rsrc"),
                "ticker": ticker,
                "doc_type": row["doc_type"],
                "source_key": source_key,
                "fiscal_period": row.get("fiscal_period"),
                "published_at": row.get("published_at"),
                "title": str(row.get("title") or ""),
                "url": row.get("url"),
                "excerpt": str(row.get("excerpt") or ""),
                "body": str(row.get("body") or ""),
                "source_provider": str(row.get("source_provider") or "unknown"),
                "metadata": dict(row.get("metadata") or {}),
                "captured_at": row.get("captured_at") or _now(),
            }
        )
        self.source_documents[stored["id"]] = stored
        return _copy(stored)

    def list_source_documents(self, ticker: str, doc_type: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.source_documents.values() if row["ticker"] == ticker.upper()]
        if doc_type:
            rows = [row for row in rows if row["doc_type"] == doc_type]
        rows.sort(key=lambda item: str(item.get("published_at") or ""), reverse=True)
        return [_copy(row) for row in rows]

    def insert_backfill(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("rbfl"),
            "ticker": str(row["ticker"]).upper(),
            "status": row.get("status") or "pending",
            "steps": dict(row.get("steps") or {}),
            "started_at": row.get("started_at") or _now(),
            "finished_at": row.get("finished_at"),
            "error": row.get("error"),
            "workflow_run_id": row.get("workflow_run_id"),
        }
        self.backfills[stored["id"]] = stored
        return _copy(stored)

    def update_backfill(
        self,
        backfill_id: str,
        *,
        status: str | None = None,
        steps: dict[str, Any] | None = None,
        error: str | None = None,
        finished_at: Any = None,
    ) -> dict[str, Any]:
        row = self.backfills.get(backfill_id)
        if row is None:
            raise DatabaseError(f"backfill not found: {backfill_id}")
        if status is not None:
            row["status"] = status
        if steps is not None:
            row["steps"] = dict(steps)
        if error is not None:
            row["error"] = error
        if finished_at is not None:
            row["finished_at"] = finished_at
        return _copy(row)

    def latest_backfill(self, ticker: str) -> dict[str, Any] | None:
        rows = [row for row in self.backfills.values() if row["ticker"] == ticker.upper()]
        if not rows:
            return None
        rows.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return _copy(rows[0])

    def list_backfills(self, ticker: str) -> list[dict[str, Any]]:
        rows = [row for row in self.backfills.values() if row["ticker"] == ticker.upper()]
        rows.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return [_copy(row) for row in rows[:20]]

    def insert_assumption_proposal(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = {
            "id": row.get("id") or new_id("rap"),
            "ticker": str(row["ticker"]).upper(),
            "assumption_id": row["assumption_id"],
            "current_status": row.get("current_status") or "unverified",
            "proposed_status": row["proposed_status"],
            "reason": row["reason"],
            "confidence": row.get("confidence"),
            "current_confidence": row.get("current_confidence"),
            "confidence_delta": row.get("confidence_delta"),
            "reasoning": dict(row.get("reasoning") or {}),
            "supporting_count": int(row.get("supporting_count") or 0),
            "opposing_count": int(row.get("opposing_count") or 0),
            "contextual_count": int(row.get("contextual_count") or 0),
            "unresolved_gaps": list(row.get("unresolved_gaps") or []),
            "produced_by": row.get("produced_by") or "assumption_engine",
            "workflow_run_id": row.get("workflow_run_id"),
            "agent_run_id": row.get("agent_run_id"),
            "created_at": _now(),
        }
        self.assumption_proposals[stored["id"]] = stored
        return _copy(stored)

    def list_assumption_proposals(self, ticker: str, workflow_run_id: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.assumption_proposals.values() if row["ticker"] == ticker.upper()]
        if workflow_run_id:
            rows = [row for row in rows if row.get("workflow_run_id") == workflow_run_id]
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return [_copy(row) for row in rows]

    def insert_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot_id = row.get("snapshot_id") or row.get("id") or new_id("rsnap")
        stored = {
            "snapshot_id": snapshot_id,
            "id": snapshot_id,
            "ticker": str(row["ticker"]).upper(),
            "created_at": row.get("created_at") or _now(),
            "workflow_run_id": row.get("workflow_run_id"),
            "pack_id": row.get("pack_id"),
            "pack_version": row.get("pack_version"),
            "pack_payload": _copy(row.get("pack_payload") or row.get("pack") or {}),
            "pack": _copy(row.get("pack") or row.get("pack_payload") or {}),
            "evidence_ids": list(row.get("evidence_ids") or []),
            "evidence_payload": _copy(row.get("evidence_payload") or row.get("evidence") or []),
            "evidence": _copy(row.get("evidence") or row.get("evidence_payload") or []),
            "assumption_ids": list(row.get("assumption_ids") or []),
            "assumption_payload": _copy(row.get("assumption_payload") or row.get("assumptions") or []),
            "assumptions": _copy(row.get("assumptions") or row.get("assumption_payload") or []),
            "findings_payload": _copy(row.get("findings_payload") or row.get("findings") or []),
            "findings": _copy(row.get("findings") or row.get("findings_payload") or []),
            "assumption_engine": _copy(row.get("assumption_engine") or []),
            "competing_hypotheses": _copy(row.get("competing_hypotheses") or []),
            "economic_drivers": _copy(row.get("economic_drivers") or []),
            "agent_reasoning": _copy(row.get("agent_reasoning") or []),
            "market_data_timestamp": row.get("market_data_timestamp"),
            "spot_price": row.get("spot_price"),
            "valuation_input_version": row.get("valuation_input_version"),
            "valuation_method_version": row.get("valuation_method_version"),
            "valuation_id": row.get("valuation_id"),
            "is_fixture": bool(row.get("is_fixture")),
            "snapshot_status": row.get("snapshot_status") or "valid",
            "invalid_reasons": list(row.get("invalid_reasons") or []),
            "pack_latest_report_date": row.get("pack_latest_report_date"),
            "pack_updated_at": row.get("pack_updated_at"),
            "source": row.get("source") or ("fixture" if row.get("is_fixture") else "production"),
            "manifest": dict(row.get("manifest") or {}),
            "model": row.get("model"),
            "prompt_version": row.get("prompt_version"),
            "pack_fingerprint": row.get("pack_fingerprint"),
            "market_comparison": dict(row.get("market_comparison") or {}),
        }
        self.snapshots[snapshot_id] = stored
        return _copy(stored)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self.snapshots.get(snapshot_id)
        return _copy(row) if row else None

    def get_snapshot_for_workflow(self, workflow_run_id: str) -> dict[str, Any] | None:
        rows = [row for row in self.snapshots.values() if row.get("workflow_run_id") == workflow_run_id]
        if not rows:
            return None
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return _copy(rows[-1])

    def get_latest_snapshot(self, ticker: str, *, include_fixture: bool = False) -> dict[str, Any] | None:
        rows = [row for row in self.snapshots.values() if row["ticker"] == ticker.upper()]
        if not include_fixture:
            rows = [row for row in rows if not row.get("is_fixture")]
        if not rows:
            return None
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return _copy(rows[-1])

    def list_snapshots(self, ticker: str, *, include_fixture: bool = False) -> list[dict[str, Any]]:
        rows = [row for row in self.snapshots.values() if row["ticker"] == ticker.upper()]
        if not include_fixture:
            rows = [row for row in rows if not row.get("is_fixture")]
        rows.sort(key=lambda item: str(item.get("created_at") or ""))
        return [_copy(row) for row in rows]

    def update_snapshot(self, snapshot_id: str, **fields: Any) -> dict[str, Any]:
        row = self.snapshots.get(snapshot_id)
        if row is None:
            raise DatabaseError(f"snapshot not found: {snapshot_id}")
        allowed = {
            "valuation_id",
            "valuation_method_version",
            "manifest",
            "model",
            "prompt_version",
            "snapshot_status",
            "invalid_reasons",
        }
        for key, value in fields.items():
            if key in allowed:
                row[key] = value
        return _copy(row)
