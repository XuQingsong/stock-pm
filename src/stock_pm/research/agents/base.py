from __future__ import annotations

from typing import Any, Protocol

from ..schema import validate_agent_output
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
        enriched = self._maybe_complete(payload, grounded)
        merged = self.merge(grounded, enriched)
        merged.agent_name = self.name
        merged.prompt_version = merged.prompt_version or self.prompt_version
        return validate_agent_output(merged, agent_name=self.name)

    def observe(self, payload: AgentInput) -> AgentOutput:
        raise NotImplementedError

    def merge(self, grounded: AgentOutput, enriched: AgentOutput | None) -> AgentOutput:
        if enriched is None:
            return grounded
        seen_facts = {str(item.get("fact") or "") for item in grounded.new_evidence}
        extra_evidence = [
            item for item in enriched.new_evidence if str(item.get("fact") or "") not in seen_facts
        ]
        seen_statements = {str(item.get("statement") or "") for item in grounded.new_assumptions}
        extra_assumptions = [
            item for item in enriched.new_assumptions if str(item.get("statement") or "") not in seen_statements
        ]
        follow_ups = list(grounded.follow_up_tasks) + list(enriched.follow_up_tasks)
        return AgentOutput(
            findings=list(dict.fromkeys(list(grounded.findings) + list(enriched.findings))),
            new_evidence=list(grounded.new_evidence) + extra_evidence,
            new_assumptions=list(grounded.new_assumptions) + extra_assumptions,
            supported_assumption_ids=list(
                dict.fromkeys(list(grounded.supported_assumption_ids) + list(enriched.supported_assumption_ids))
            ),
            challenged_assumption_ids=list(
                dict.fromkeys(list(grounded.challenged_assumption_ids) + list(enriched.challenged_assumption_ids))
            ),
            assumption_links=list(grounded.assumption_links) + list(enriched.assumption_links),
            proposed_assumption_changes=list(grounded.proposed_assumption_changes)
            + list(enriched.proposed_assumption_changes),
            follow_up_tasks=follow_ups,
            missing_data=list(dict.fromkeys(list(grounded.missing_data) + list(enriched.missing_data))),
            confidence=enriched.confidence if enriched.confidence is not None else grounded.confidence,
            agent_name=self.name,
            model=enriched.model or grounded.model,
            prompt_version=self.prompt_version,
        )

    def _maybe_complete(self, payload: AgentInput, grounded: AgentOutput) -> AgentOutput | None:
        if self.completer is None or not self.system_prompt:
            return None
        from ..schema import output_from_payload

        user = self.user_prompt(payload, grounded)
        result = self.completer.complete_json(
            system=self.system_prompt,
            user=user,
            schema=AGENT_OUTPUT_SCHEMA,
        )
        if result.get("status") != "ok" or not isinstance(result.get("payload"), dict):
            return None
        try:
            output = output_from_payload(result["payload"], agent_name=self.name)
        except Exception:
            return None
        output.model = result.get("model")
        output.prompt_version = self.prompt_version
        return output

    def user_prompt(self, payload: AgentInput, grounded: AgentOutput) -> str:
        import json

        from ..types import to_plain

        return json.dumps(
            {
                "ticker": payload.ticker,
                "task": payload.task,
                "research_pack": payload.research_pack,
                "assumptions": payload.assumptions,
                "evidence": payload.evidence,
                "deterministic_findings": to_plain(grounded),
            },
            ensure_ascii=False,
            default=str,
        )
