"""Research service: provenance, PM write gate, versioning, follow-up tasks."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from datetime import datetime, timezone

from .classify import classify_from_issuer, classify_template
from .errors import CrossTickerError, DepthLimitError, ProvenanceError, ResearchPermissionError
from .evidence import evidence_fingerprint
from .issuer import IDENTITY_FIELD_KEYS, fill_issuer_identity, merge_identity
from .pack_builder import PACK_CONTENT_FIELDS, PackBuilder, default_pack_source
from .types import (
    ACTOR_API,
    ACTOR_PM,
    ASSUMPTION_STATUSES,
    IMPORTANCE_LEVELS,
    LINK_DIRECTIONS,
    LINK_STRENGTHS,
    THESIS_ROLES,
    AgentOutput,
    FollowUpSpec,
    follow_up_from_payload,
    normalize_valuation_case,
    to_plain,
)


def _ticker(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        raise ProvenanceError("ticker is required")
    return text


def _require_text(payload: dict[str, Any], key: str) -> str:
    text = str(payload.get(key) or "").strip()
    if not text:
        raise ProvenanceError(f"{key} is required")
    return text


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ResearchService:
    def __init__(self, store: Any, *, pack_source: Any | None = None, completer: Any | None = None) -> None:
        self.store = store
        self.pack_source = pack_source
        self.completer = completer

    def _audit(
        self,
        *,
        ticker: str,
        agent_name: str,
        workflow_run_id: str | None = None,
        task_id: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        payload: Any = None,
        output: Any = None,
        confidence: float | None = None,
        status: str = "success",
    ) -> dict[str, Any]:
        started = self.store.insert_agent_run(
            {
                "ticker": ticker,
                "agent_name": agent_name,
                "workflow_run_id": workflow_run_id,
                "task_id": task_id,
                "model": model,
                "prompt_version": prompt_version,
                "input_hash": _hash_payload(payload),
                "status": "running",
            }
        )
        return self.store.complete_agent_run(
            started["id"],
            status=status,
            output_json=to_plain(output) if output is not None else {},
            confidence=confidence,
        )

    def ensure_issuer(self, ticker: str, **fields: Any) -> dict[str, Any]:
        symbol = _ticker(ticker)
        explicit = {key: value for key, value in fields.items() if key in IDENTITY_FIELD_KEYS}
        existing = self.store.get_issuer(symbol)
        if existing:
            merged = fill_issuer_identity(existing, symbol, **explicit)
        else:
            merged = merge_identity(symbol, **explicit)
        stored = self.store.upsert_issuer(merged)
        pack = self.store.get_pack(symbol)
        if pack is None:
            self.ensure_pack_shell(symbol, issuer=stored)
        return stored

    def get_issuer(self, ticker: str) -> dict[str, Any] | None:
        return self.store.get_issuer(_ticker(ticker))

    def ensure_pack_shell(self, ticker: str, *, issuer: dict[str, Any] | None = None, workflow_run_id: str | None = None) -> dict[str, Any]:
        symbol = _ticker(ticker)
        profile = issuer or self.store.get_issuer(symbol) or merge_identity(symbol)
        template_id = classify_from_issuer(profile)
        missing = list(PACK_CONTENT_FIELDS)
        if profile.get("missing_fields"):
            missing = ["issuer." + item for item in profile["missing_fields"]] + missing
        return self.store.upsert_pack(
            {
                "ticker": symbol,
                "template_id": template_id,
                "company_profile": {
                    "legal_name": profile.get("legal_name"),
                    "cik": profile.get("cik"),
                    "fiscal_year_end_month": profile.get("fiscal_year_end_month"),
                    "sector": profile.get("sector"),
                    "asset_class": profile.get("asset_class"),
                },
                "missing_fields": missing,
                "source_refs": {"issuer_profiles": symbol},
                "workflow_run_id": workflow_run_id,
            }
        )

    def get_pack(self, ticker: str) -> dict[str, Any]:
        symbol = _ticker(ticker)
        pack = self.store.get_pack(symbol)
        if pack:
            return pack
        return {
            "ticker": symbol,
            "status": "missing",
            "template_id": classify_template(),
            "missing_fields": list(PACK_CONTENT_FIELDS) + ["issuer_profile"],
        }

    def build_pack(self, ticker: str, *, workflow_run_id: str | None = None) -> dict[str, Any]:
        symbol = _ticker(ticker)
        issuer = self.get_issuer(symbol) or self.ensure_issuer(symbol)
        source = self.pack_source or default_pack_source(self.store)
        snapshot = PackBuilder(source).build(symbol, issuer=issuer, workflow_run_id=workflow_run_id)
        stored = self.store.upsert_pack(snapshot)
        self._audit(
            ticker=symbol,
            agent_name="pack_builder",
            workflow_run_id=workflow_run_id,
            payload={"op": "build_pack", "missing_fields": stored.get("missing_fields")},
            output={"template_id": stored.get("template_id")},
        )
        return stored

    def research_snapshot(self, ticker: str, workflow_run_id: str | None = None) -> dict[str, Any]:
        symbol = _ticker(ticker)
        pack = self.get_pack(symbol)
        assumptions = []
        for row in self.store.list_assumptions(symbol):
            links = self.store.list_links(assumption_id=row["id"])
            item = dict(row)
            item["supporting_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "support"]
            item["counter_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "oppose"]
            item["contextual_evidence_ids"] = [link["evidence_id"] for link in links if link["direction"] == "contextual"]
            item["links"] = links
            assumptions.append(item)
        agent_runs = self.store.list_agent_runs(symbol, workflow_run_id)
        findings = []
        for run in agent_runs:
            payload = run.get("output_json") or {}
            for item in payload.get("findings") or []:
                findings.append({"agent": run.get("agent_name"), "text": item, "agent_run_id": run.get("id")})
        return {
            "ticker": symbol,
            "pack": pack,
            "findings": findings,
            "evidence": self.store.list_evidence(symbol),
            "assumptions": assumptions,
            "tasks": self.store.list_tasks(symbol, workflow_run_id),
            "workflow_runs": self.store.list_workflow_runs(symbol),
            "agent_runs": agent_runs,
            "backfill": self.store.latest_backfill(symbol) if hasattr(self.store, "latest_backfill") else None,
        }

    def start_workflow_run(
        self,
        ticker: str,
        *,
        workflow_name: str = "new_ticker_research",
        trigger: str = "api",
        template_id: str | None = None,
        max_depth: int = 4,
        max_tasks: int = 32,
    ) -> dict[str, Any]:
        symbol = _ticker(ticker)
        issuer = self.ensure_issuer(symbol)
        template = template_id or classify_from_issuer(issuer)
        self.ensure_pack_shell(symbol, issuer=issuer)
        return self.store.insert_workflow_run(
            {
                "ticker": symbol,
                "workflow_name": workflow_name,
                "trigger": trigger,
                "template_id": template,
                "config_json": {"max_depth": max_depth, "max_tasks": max_tasks},
            }
        )

    def create_task(self, ticker: str, body: dict[str, Any], *, actor: str = ACTOR_API) -> dict[str, Any]:
        symbol = _ticker(ticker)
        parent_id = body.get("parent_task_id")
        parent = self.store.get_task(parent_id) if parent_id else None
        depth = int(body.get("depth") or 0)
        root_id = body.get("root_task_id")
        if parent:
            if parent["ticker"] != symbol:
                raise CrossTickerError("follow-up task ticker must match parent")
            depth = int(parent.get("depth") or 0) + 1
            root_id = parent.get("root_task_id") or parent["id"]
            body = {**body, "workflow_run_id": body.get("workflow_run_id") or parent.get("workflow_run_id")}
        max_depth = body.get("max_depth")
        if max_depth is not None and depth > int(max_depth):
            raise DepthLimitError(f"follow-up depth {depth} exceeds max_depth {max_depth}")
        task = self.store.insert_task(
            {
                "ticker": symbol,
                "workflow_run_id": body.get("workflow_run_id"),
                "parent_task_id": parent["id"] if parent else parent_id,
                "root_task_id": root_id,
                "depth": depth,
                "task_type": _require_text(body, "task_type"),
                "title": _require_text(body, "title"),
                "description": body.get("description") or "",
                "source_reason": body.get("source_reason") or "",
                "required_data": body.get("required_data") or [],
                "assigned_agents": body.get("assigned_agents") or [],
                "priority": body.get("priority") or 50,
                "created_by": actor,
            }
        )
        self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=task.get("workflow_run_id"),
            task_id=task["id"],
            model=body.get("model"),
            prompt_version=body.get("prompt_version"),
            payload={"op": "create_task", "title": task["title"]},
            output={"task_id": task["id"], "depth": task["depth"]},
        )
        return task

    def enqueue_follow_ups(
        self,
        parent: dict[str, Any],
        specs: list[FollowUpSpec | dict[str, Any]],
        *,
        max_depth: int,
        actor: str,
        agent_run_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        created: list[dict[str, Any]] = []
        dropped = 0
        for item in specs:
            spec = follow_up_from_payload(item)
            depth = int(parent.get("depth") or 0) + 1
            if depth > max_depth:
                dropped += 1
                continue
            created.append(
                self.create_task(
                    parent["ticker"],
                    {
                        "parent_task_id": parent["id"],
                        "workflow_run_id": parent.get("workflow_run_id"),
                        "task_type": spec.task_type,
                        "title": spec.title,
                        "description": spec.description,
                        "source_reason": spec.source_reason,
                        "required_data": list(spec.required_data),
                        "assigned_agents": list(spec.assigned_agents),
                        "priority": spec.priority,
                        "max_depth": max_depth,
                        "model": None,
                        "prompt_version": None,
                    },
                    actor=actor,
                )
            )
        del agent_run_id
        return created, dropped

    def create_evidence(self, ticker: str, body: dict[str, Any], *, actor: str = ACTOR_API) -> dict[str, Any]:
        symbol = _ticker(ticker)
        if not body.get("source_time") or not body.get("retrieved_at"):
            raise ProvenanceError("evidence requires source_time and retrieved_at")
        _require_text(body, "fact")
        _require_text(body, "source")
        _require_text(body, "evidence_type")
        audit = self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=body.get("workflow_run_id"),
            task_id=body.get("task_id"),
            model=body.get("model"),
            prompt_version=body.get("prompt_version"),
            payload={"op": "create_evidence", "fact": body.get("fact")},
        )
        evidence = self.store.insert_evidence(
            {
                "ticker": symbol,
                "evidence_type": _require_text(body, "evidence_type"),
                "fact": _require_text(body, "fact"),
                "source": _require_text(body, "source"),
                "source_url": body.get("source_url"),
                "source_time": body.get("source_time"),
                "retrieved_at": body.get("retrieved_at"),
                "confidence": body.get("confidence"),
                "importance": body.get("importance") or "medium",
                "direction": body.get("direction") or "neutral",
                "raw_reference": body.get("raw_reference") or {},
                "produced_by": actor,
                "task_id": body.get("task_id"),
                "workflow_run_id": body.get("workflow_run_id"),
                "agent_run_id": audit["id"],
                "model": body.get("model"),
                "prompt_version": body.get("prompt_version"),
            }
        )
        if not evidence.get("source_time") or not evidence.get("retrieved_at"):
            raise ProvenanceError("evidence requires source_time and retrieved_at")
        return evidence

    def create_assumption(self, ticker: str, body: dict[str, Any], *, actor: str = ACTOR_API) -> dict[str, Any]:
        symbol = _ticker(ticker)
        importance = body.get("importance") or "medium"
        if importance not in IMPORTANCE_LEVELS:
            raise ProvenanceError("invalid importance")
        role = body.get("thesis_role") or "supporting"
        if role not in THESIS_ROLES:
            raise ProvenanceError("invalid thesis_role")
        if role == "core" and actor != ACTOR_PM:
            raise ResearchPermissionError("only pm_judge can mark an assumption as core")
        audit = self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=body.get("workflow_run_id"),
            model=body.get("model"),
            prompt_version=body.get("prompt_version"),
            payload={"op": "create_assumption", "statement": body.get("statement")},
        )
        return self.store.insert_assumption(
            {
                "ticker": symbol,
                "category": body.get("category") or "other",
                "statement": _require_text(body, "statement"),
                "status": "unverified",
                "importance": importance,
                "thesis_role": role,
                "confidence": body.get("confidence"),
                "next_verification": body.get("next_verification"),
                "proposed_by": actor,
                "workflow_run_id": body.get("workflow_run_id"),
                "agent_run_id": audit["id"],
                "model": body.get("model"),
                "prompt_version": body.get("prompt_version"),
            }
        )

    def link_assumption_evidence(
        self,
        ticker: str,
        *,
        assumption_id: str,
        evidence_id: str,
        direction: str,
        strength: str | None = None,
        reason: str | None = None,
        actor: str = ACTOR_API,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        symbol = _ticker(ticker)
        if direction not in LINK_DIRECTIONS:
            raise ProvenanceError("link direction must be support, oppose, or contextual")
        resolved_strength = (strength or "moderate").strip() or "moderate"
        if resolved_strength not in LINK_STRENGTHS:
            raise ProvenanceError("link strength must be strong, moderate, or weak")
        assumption = self.store.get_assumption(assumption_id)
        evidence = self.store.get_evidence(evidence_id)
        if assumption is None or evidence is None:
            raise ProvenanceError("assumption and evidence must exist before linking")
        if assumption["ticker"] != symbol or evidence["ticker"] != symbol:
            raise CrossTickerError("assumption and evidence must belong to the same ticker")
        if assumption["ticker"] != evidence["ticker"]:
            raise CrossTickerError("cannot link evidence across tickers")
        audit = self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=workflow_run_id or assumption.get("workflow_run_id"),
            payload={
                "op": "link",
                "assumption_id": assumption_id,
                "evidence_id": evidence_id,
                "direction": direction,
                "strength": resolved_strength,
            },
            output={"linked": True},
        )
        return self.store.insert_link(
            {
                "assumption_id": assumption_id,
                "evidence_id": evidence_id,
                "direction": direction,
                "strength": resolved_strength,
                "reason": reason,
                "linked_by": actor,
                "workflow_run_id": workflow_run_id or assumption.get("workflow_run_id"),
                "agent_run_id": audit["id"],
            }
        )

    def update_assumption_status(
        self,
        ticker: str,
        assumption_id: str,
        *,
        actor: str,
        status: str,
        importance: str | None = None,
        thesis_role: str | None = None,
        confidence: float | None = None,
        next_verification: str | None = None,
    ) -> dict[str, Any]:
        symbol = _ticker(ticker)
        if actor != ACTOR_PM:
            raise ResearchPermissionError("only pm_judge can update assumption status or core role")
        if status not in ASSUMPTION_STATUSES:
            raise ProvenanceError("invalid assumption status")
        assumption = self.store.get_assumption(assumption_id)
        if assumption is None or assumption["ticker"] != symbol:
            raise CrossTickerError("assumption ticker mismatch")
        if status != "unverified":
            links = self.store.list_links(assumption_id=assumption_id)
            if not links:
                raise ProvenanceError("status change requires at least one assumption_evidence_link")
        fields: dict[str, Any] = {"status": status, "status_updated_by": actor}
        if importance:
            if importance not in IMPORTANCE_LEVELS:
                raise ProvenanceError("invalid importance")
            fields["importance"] = importance
        if thesis_role:
            if thesis_role not in THESIS_ROLES:
                raise ProvenanceError("invalid thesis_role")
            fields["thesis_role"] = thesis_role
        if confidence is not None:
            fields["confidence"] = confidence
        if next_verification is not None:
            fields["next_verification"] = next_verification
        updated = self.store.update_assumption(assumption_id, **fields)
        self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=updated.get("workflow_run_id"),
            payload={"op": "assumption_status", "id": assumption_id, "status": status},
            output={"status": updated["status"], "thesis_role": updated["thesis_role"]},
        )
        return updated

    def create_thesis(self, ticker: str, body: dict[str, Any], *, actor: str) -> dict[str, Any]:
        symbol = _ticker(ticker)
        if actor != ACTOR_PM:
            raise ResearchPermissionError("only pm_judge can write an investment thesis")
        key_ids = [str(item) for item in (body.get("key_assumption_ids") or [])]
        for assumption_id in key_ids:
            assumption = self.store.get_assumption(assumption_id)
            if assumption is None or assumption["ticker"] != symbol:
                raise CrossTickerError("thesis key assumptions must exist on the same ticker")
            if assumption.get("thesis_role") != "core":
                self.store.update_assumption(assumption_id, thesis_role="core", status_updated_by=actor)
        version = self.store.next_thesis_version(symbol)
        previous = self.store.get_latest_thesis(symbol)
        change = body.get("change_summary")
        if not change and previous:
            change = "thesis version incremented"
        audit = self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=body.get("workflow_run_id"),
            model=body.get("model"),
            prompt_version=body.get("prompt_version"),
            payload={"op": "create_thesis", "version": version},
        )
        return self.store.insert_thesis(
            {
                "ticker": symbol,
                "version": version,
                "short_term_view": body.get("short_term_view") or "",
                "mid_term_view": body.get("mid_term_view") or "",
                "long_term_view": body.get("long_term_view") or "",
                "core_thesis": _require_text(body, "core_thesis"),
                "key_assumption_ids": key_ids,
                "key_risks": body.get("key_risks") or [],
                "invalidation_conditions": body.get("invalidation_conditions") or [],
                "monitoring_items": body.get("monitoring_items") or [],
                "confidence": body.get("confidence"),
                "change_summary": change,
                "actor": actor,
                "workflow_run_id": body.get("workflow_run_id"),
                "agent_run_id": audit["id"],
                "model": body.get("model"),
                "prompt_version": body.get("prompt_version"),
            }
        )

    def create_valuation(self, ticker: str, body: dict[str, Any], *, actor: str = ACTOR_PM) -> dict[str, Any]:
        symbol = _ticker(ticker)
        if actor != ACTOR_PM:
            raise ResearchPermissionError("only pm_judge can write valuation")
        thesis_id = body.get("thesis_id")
        thesis = self.store.get_thesis(thesis_id) if thesis_id else self.store.get_latest_thesis(symbol)
        if thesis is None or thesis["ticker"] != symbol:
            raise ProvenanceError("valuation requires an existing thesis on this ticker")
        for key in ("bear_case", "base_case", "bull_case"):
            if key not in body:
                raise ProvenanceError("valuation requires bear_case, base_case, and bull_case")
        audit = self._audit(
            ticker=symbol,
            agent_name=actor,
            workflow_run_id=body.get("workflow_run_id"),
            model=body.get("model"),
            prompt_version=body.get("prompt_version"),
            payload={"op": "create_valuation", "thesis_id": thesis["id"]},
        )
        valuation = self.store.insert_valuation(
            {
                "ticker": symbol,
                "thesis_id": thesis["id"],
                "thesis_version": thesis["version"],
                "horizon": body.get("horizon") or "2y",
                "bear_case": normalize_valuation_case(body.get("bear_case")),
                "base_case": normalize_valuation_case(body.get("base_case")),
                "bull_case": normalize_valuation_case(body.get("bull_case")),
                "spot_price": body.get("spot_price"),
                "actor": actor,
                "workflow_run_id": body.get("workflow_run_id"),
                "agent_run_id": audit["id"],
                "model": body.get("model"),
                "prompt_version": body.get("prompt_version"),
            }
        )
        self.store.bind_thesis_valuation(thesis["id"], valuation["id"])
        return valuation

    def persist_agent_output(
        self,
        task: dict[str, Any],
        output: AgentOutput,
        *,
        agent_run_id: str,
        max_depth: int,
    ) -> dict[str, Any]:
        ticker = task["ticker"]
        actor = output.agent_name or task.get("created_by") or "agent"
        retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        existing_evidence = {evidence_fingerprint(row): row["id"] for row in self.store.list_evidence(ticker)}
        key_to_id: dict[str, str] = {}
        evidence_rows = []
        for item in output.new_evidence:
            payload = dict(item)
            local_key = str(payload.pop("_key", "") or "")
            payload.setdefault("retrieved_at", retrieved_at)
            payload.setdefault("workflow_run_id", task.get("workflow_run_id"))
            payload.setdefault("task_id", task["id"])
            payload.setdefault("model", output.model)
            payload.setdefault("prompt_version", output.prompt_version)
            fingerprint = evidence_fingerprint(payload)
            if fingerprint in existing_evidence:
                evidence_id = existing_evidence[fingerprint]
                if local_key:
                    key_to_id[local_key] = evidence_id
                key_to_id[evidence_id] = evidence_id
                continue
            try:
                row = self.create_evidence(ticker, payload, actor=actor)
            except ProvenanceError:
                continue
            evidence_rows.append(row)
            existing_evidence[fingerprint] = row["id"]
            key_to_id[row["id"]] = row["id"]
            if local_key:
                key_to_id[local_key] = row["id"]

        existing_assumptions = {row["statement"]: row for row in self.store.list_assumptions(ticker)}
        assumption_rows = []
        linked_pairs: set[tuple[str, str, str]] = set()

        def _link(assumption_id: str, evidence_id: str, *, direction: str, strength: str | None = None, reason: str | None = None) -> None:
            pair = (assumption_id, evidence_id, direction)
            if not assumption_id or not evidence_id or pair in linked_pairs:
                return
            try:
                self.link_assumption_evidence(
                    ticker,
                    assumption_id=assumption_id,
                    evidence_id=evidence_id,
                    direction=direction,
                    strength=strength,
                    reason=reason,
                    actor=actor,
                    workflow_run_id=task.get("workflow_run_id"),
                )
            except (ProvenanceError, CrossTickerError):
                return
            linked_pairs.add(pair)

        for item in output.new_assumptions:
            payload = dict(item)
            links = list(payload.pop("links", []) or [])
            payload.pop("_key", None)
            payload.setdefault("workflow_run_id", task.get("workflow_run_id"))
            payload.setdefault("model", output.model)
            payload.setdefault("prompt_version", output.prompt_version)
            statement = str(payload.get("statement") or "").strip()
            existing = existing_assumptions.get(statement)
            if existing:
                row = existing
            else:
                try:
                    row = self.create_assumption(ticker, payload, actor=actor)
                except (ProvenanceError, ResearchPermissionError):
                    continue
                existing_assumptions[statement] = row
            assumption_rows.append(row)
            for link in links:
                evid = key_to_id.get(str(link.get("evidence_key") or "")) or link.get("evidence_id")
                if evid:
                    _link(row["id"], str(evid), direction=str(link.get("direction") or "support"), strength=link.get("strength"), reason=link.get("reason"))

        statement_to_id = {row["statement"]: row["id"] for row in existing_assumptions.values()}
        for link in output.assumption_links:
            assumption_id = str(link.get("assumption_id") or statement_to_id.get(str(link.get("statement") or "")) or "")
            evid = key_to_id.get(str(link.get("evidence_key") or "")) or link.get("evidence_id")
            if assumption_id and evid:
                _link(assumption_id, str(evid), direction=str(link.get("direction") or "support"), strength=link.get("strength"), reason=link.get("reason"))
        for assumption_id in output.supported_assumption_ids:
            for row in evidence_rows[:2]:
                _link(str(assumption_id), row["id"], direction="support", reason="agent marked supporting")
        for assumption_id in output.challenged_assumption_ids:
            for row in evidence_rows[:2]:
                _link(str(assumption_id), row["id"], direction="oppose", reason="agent marked challenging")

        follow_specs: list[FollowUpSpec] = []
        for item in output.follow_up_tasks:
            spec = follow_up_from_payload(item)
            required = []
            for raw in spec.required_data:
                text = str(raw)
                if text.startswith("assumption:") and "rasm_" not in text:
                    needle = text.split(":", 1)[1]
                    match = next(
                        (
                            assumption_id
                            for statement, assumption_id in statement_to_id.items()
                            if statement.startswith(needle) or needle.startswith(statement[:48])
                        ),
                        None,
                    )
                    required.append(f"assumption:{match}" if match else text)
                else:
                    required.append(text)
            follow_specs.append(
                FollowUpSpec(
                    title=spec.title,
                    description=spec.description,
                    task_type=spec.task_type,
                    assigned_agents=spec.assigned_agents,
                    required_data=tuple(required),
                    priority=spec.priority,
                    source_reason=spec.source_reason,
                )
            )
        follow_ups, dropped = self.enqueue_follow_ups(
            task,
            follow_specs,
            max_depth=max_depth,
            actor=actor,
            agent_run_id=agent_run_id,
        )
        return {
            "evidence": evidence_rows,
            "assumptions": assumption_rows,
            "follow_ups": follow_ups,
            "dropped_follow_ups": dropped,
            "missing_data": list(output.missing_data),
        }

    def empty_thesis(self, ticker: str) -> dict[str, Any]:
        return {"ticker": _ticker(ticker), "status": "missing", "version": None, "core_thesis": None}

    def empty_valuation(self, ticker: str) -> dict[str, Any]:
        return {"ticker": _ticker(ticker), "status": "missing", "bear_case": None, "base_case": None, "bull_case": None}
