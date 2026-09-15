from __future__ import annotations

from typing import Any, Protocol

from ..llm_reason import audit_from_result, skipped_audit
from ..schema import output_from_payload, validate_agent_output
from ..types import AGENT_OUTPUT_SCHEMA, AgentInput, AgentOutput


class JsonCompleter(Protocol):
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class SettingsCompleter:
    """Adapter over stock_pm.llm.complete_json. Agents never import provider URLs."""

    def __init__(self, settings: Any | None = None) -> None:
        self.settings = settings

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from stock_pm.llm import complete_json

        return complete_json(system=system, user=user, schema=schema, settings=self.settings)


class BaseAgent:
    name = "agent"
    prompt_version = "sprint2-v1"

    def __init__(self, completer: JsonCompleter | None = None, system_prompt: str = "") -> None:
        self.completer = completer
        self.system_prompt = system_prompt

    def run(self, payload: AgentInput) -> AgentOutput:
        grounded = self.observe(payload)
        enriched, audit = self._maybe_complete(payload, grounded)
        merged = self.merge(grounded, enriched)
        merged.agent_name = self.name
        merged.prompt_version = merged.prompt_version or self.prompt_version
        merged.llm_audit = audit
        merged.reasoning = dict(merged.reasoning or {})
        merged.reasoning["llm_audit"] = audit
        merged.model = audit.get("model") or merged.model
        merged.reasoning["fallback"] = audit.get("llm_status") != "ok"
        return validate_agent_output(merged, agent_name=self.name)

    def observe(self, payload: AgentInput) -> AgentOutput:
        raise NotImplementedError

    def merge(self, grounded: AgentOutput, enriched: AgentOutput | None) -> AgentOutput:
        """LLM may add findings, links, and proposals. It may not mint Evidence."""
        if enriched is None:
            return grounded
        follow_ups = list(grounded.follow_up_tasks) + list(enriched.follow_up_tasks)
        links = list(enriched.assumption_links or []) or list(grounded.assumption_links)
        proposals = list(enriched.proposed_assumption_changes or []) or list(grounded.proposed_assumption_changes)
        reasoning = dict(grounded.reasoning or {})
        reasoning.update(enriched.reasoning or {})
        return AgentOutput(
            findings=list(dict.fromkeys(list(grounded.findings) + list(enriched.findings))),
            new_evidence=list(grounded.new_evidence),
            new_assumptions=list(grounded.new_assumptions),
            supported_assumption_ids=list(
                dict.fromkeys(list(grounded.supported_assumption_ids) + list(enriched.supported_assumption_ids))
            ),
            challenged_assumption_ids=list(
                dict.fromkeys(list(grounded.challenged_assumption_ids) + list(enriched.challenged_assumption_ids))
            ),
            assumption_links=links,
            proposed_assumption_changes=proposals,
            follow_up_tasks=follow_ups,
            missing_data=list(dict.fromkeys(list(grounded.missing_data) + list(enriched.missing_data))),
            confidence=enriched.confidence if enriched.confidence is not None else grounded.confidence,
            agent_name=self.name,
            model=enriched.model or grounded.model,
            prompt_version=self.prompt_version,
            reasoning=reasoning,
            llm_audit=enriched.llm_audit or grounded.llm_audit,
        )

    def _maybe_complete(self, payload: AgentInput, grounded: AgentOutput) -> tuple[AgentOutput | None, dict[str, Any]]:
        if self.completer is None or not self.system_prompt:
            return None, skipped_audit(error="completer or system prompt missing")
        user = self.user_prompt(payload, grounded)
        result = self.completer.complete_json(
            system=self.system_prompt,
            user=user,
            schema=AGENT_OUTPUT_SCHEMA,
        )
        audit = audit_from_result(result)
        if result.get("status") != "ok" or not isinstance(result.get("payload"), dict):
            audit["fallback_used"] = True
            if audit["llm_status"] == "ok":
                audit["llm_status"] = "failed"
            return None, audit
        try:
            output = output_from_payload(result["payload"], agent_name=self.name)
        except Exception as exc:
            audit["llm_status"] = "fallback"
            audit["fallback_used"] = True
            audit["error"] = str(exc)
            return None, audit
        output.model = result.get("model")
        output.prompt_version = self.prompt_version
        output.new_evidence = []
        output.new_assumptions = []
        output.llm_audit = audit
        return output, audit

    def user_prompt(self, payload: AgentInput, grounded: AgentOutput) -> str:
        import json

        from ..llm_reason import compact_assumptions, compact_evidence, compact_pack
        from ..types import to_plain

        grounded_plain = to_plain(grounded)
        grounded_plain["new_evidence"] = compact_evidence(grounded.new_evidence, limit=24)
        return json.dumps(
            {
                "ticker": payload.ticker,
                "task": {
                    "task_type": (payload.task or {}).get("task_type"),
                    "title": (payload.task or {}).get("title"),
                    "description": (payload.task or {}).get("description"),
                    "required_data": (payload.task or {}).get("required_data"),
                },
                "research_pack": compact_pack(payload.research_pack),
                "assumptions": compact_assumptions(payload.assumptions),
                "evidence": compact_evidence(payload.evidence, limit=24),
                "deterministic_findings": {
                    "findings": grounded_plain.get("findings"),
                    "missing_data": grounded_plain.get("missing_data"),
                    "new_evidence": grounded_plain.get("new_evidence"),
                    "assumption_links": grounded_plain.get("assumption_links"),
                },
                "rules": [
                    "Do not invent evidence, customers, numbers, or sources.",
                    "Cite only evidence_id or evidence_key values from this JSON.",
                    "new_evidence must be empty; Python already extracted facts.",
                ],
            },
            ensure_ascii=False,
            default=str,
        )
