"""Agent registry. Workflow asks for an agent by name; agents do not call each other."""

from __future__ import annotations

from typing import Any

from .agents.base import JsonCompleter, SettingsCompleter
from .agents.fundamental import FundamentalAgent
from .agents.industry import IndustryAgent
from .agents.quant import QuantAgent
from .agents.risk import RiskAgent
from .agents.search_data import SearchDataAgent
from .schema import validate_agent_output
from .types import (
    AGENT_FUNDAMENTAL,
    AGENT_INDUSTRY,
    AGENT_QUANT,
    AGENT_RISK,
    AGENT_SEARCH,
    AgentInput,
    AgentOutput,
)


TASK_TYPE_AGENTS = {
    "discover_fundamentals": AGENT_FUNDAMENTAL,
    "industry_check": AGENT_INDUSTRY,
    "quant_price_in": AGENT_QUANT,
    "skeptic_attack": AGENT_RISK,
}


def built_in_agents(*, completer: JsonCompleter | None = None, tools: Any | None = None) -> dict[str, Any]:
    return {
        AGENT_SEARCH: SearchDataAgent(completer=completer, tools=tools),
        AGENT_FUNDAMENTAL: FundamentalAgent(completer=completer),
        AGENT_INDUSTRY: IndustryAgent(completer=completer, tools=tools),
        AGENT_QUANT: QuantAgent(),
        AGENT_RISK: RiskAgent(completer=completer, tools=tools),
    }


class AgentRuntime:
    def __init__(self, completer: JsonCompleter | None = None, agents: dict[str, Any] | None = None) -> None:
        self.completer = completer
        self.agents = agents or built_in_agents(completer=completer)

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
    task_type = str(task.get("task_type") or "")
    if task_type in TASK_TYPE_AGENTS:
        return TASK_TYPE_AGENTS[task_type]
    return AGENT_SEARCH
