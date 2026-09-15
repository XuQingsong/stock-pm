"""Agent registry. Workflow asks for an agent by name; agents do not call each other."""

from __future__ import annotations

from typing import Any

from .agents.base import JsonCompleter, SettingsCompleter
from .agents.fundamental import FundamentalAgent
from .agents.search_data import SearchDataAgent
from .schema import validate_agent_output
from .types import AGENT_FUNDAMENTAL, AGENT_SEARCH, AgentInput, AgentOutput


class AgentRuntime:
    def __init__(self, completer: JsonCompleter | None = None, agents: dict[str, Any] | None = None) -> None:
        self.completer = completer
        self.agents = agents or {
            AGENT_SEARCH: SearchDataAgent(completer=completer),
            AGENT_FUNDAMENTAL: FundamentalAgent(completer=completer),
        }

    def run(self, name: str, payload: AgentInput) -> AgentOutput:
        agent = self.agents.get(name)
        if agent is None:
            agent = self.agents[AGENT_SEARCH]
        output = agent.run(payload)
        return validate_agent_output(output, agent_name=getattr(agent, "name", name))


def default_runtime(completer: JsonCompleter | None = None) -> AgentRuntime:
    return AgentRuntime(completer=completer if completer is not None else SettingsCompleter())


def agent_name_for_task(task: dict[str, Any]) -> str:
    assigned = list(task.get("assigned_agents") or [])
    if assigned:
        return str(assigned[0])
    if str(task.get("task_type") or "") == "discover_fundamentals":
        return AGENT_FUNDAMENTAL
    return AGENT_SEARCH
