"""Brain LLM routing: mechanical vs reasoning layers via the existing gateway.

Business code never hardcodes vendor model IDs. Names come from Settings / env.
DeepSeek is not a Brain production default. Kimi is not in the production workflow.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from stock_pm.config import Settings
from stock_pm.research.agents.base import SettingsCompleter

BAILIAN_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ROLE_MECHANICAL = "mechanical"
ROLE_REASONING = "reasoning"
ROLE_CRITIC = "critic"

_MODEL_ALIASES = {
    "glm-5.2": "glm-5.2",
    "glm5.2": "glm-5.2",
    "glm_5_2": "glm-5.2",
    "zhipu-glm-5.2": "glm-5.2",
    "zhipu/glm-5.2": "glm-5.2",
    "glm-5.3": "glm-5.3",
    "glm5.3": "glm-5.3",
    "glm_5_3": "glm-5.3",
    "zhipu-glm-5.3": "glm-5.3",
    "zhipu/glm-5.3": "glm-5.3",
}

_DEFAULT_BY_ROLE = {
    ROLE_MECHANICAL: "glm-5.2",
    ROLE_REASONING: "glm-5.3",
    ROLE_CRITIC: "glm-5.3",
}

# GLM-5.3 thinking consumes completion tokens before JSON. 8192 truncates Driver/Claim/PM.
_BUDGET_BY_ROLE = {
    ROLE_MECHANICAL: {"timeout": 180, "max_tokens": 8192},
    ROLE_REASONING: {"timeout": 600, "max_tokens": 32768},
    ROLE_CRITIC: {"timeout": 300, "max_tokens": 16384},
}


def canonical_brain_model(name: str, *, role: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return _DEFAULT_BY_ROLE.get(role, _DEFAULT_BY_ROLE[ROLE_REASONING])
    return _MODEL_ALIASES.get(raw.lower(), raw)


def _credential_key(settings: Settings, explicit: str) -> str:
    return (
        (explicit or "").strip()
        or (settings.dashscope_api_key or "").strip()
        or (settings.strong_model_api_key or "").strip()
    )


def _credential_base(settings: Settings, explicit: str, *, key: str) -> str:
    base = (explicit or "").strip().rstrip("/")
    if base:
        return base
    strong = (settings.strong_model_base_url or "").strip().rstrip("/")
    if strong:
        return strong
    if key:
        return BAILIAN_COMPAT_BASE
    return ""


def layer_settings(settings: Settings | None = None, *, role: str) -> Settings:
    """Return a Settings copy pointed at the mechanical or reasoning Brain layer."""
    config = settings or Settings()
    if role not in {ROLE_MECHANICAL, ROLE_REASONING, ROLE_CRITIC}:
        raise ValueError(f"unknown brain role: {role}")
    if role == ROLE_MECHANICAL:
        name = canonical_brain_model(config.mechanical_model_name, role=role)
        provider = (config.mechanical_model_provider or "openai").strip() or "openai"
        key = _credential_key(config, config.mechanical_model_api_key)
        base = _credential_base(config, config.mechanical_model_base_url, key=key)
    else:
        name = canonical_brain_model(config.reasoning_model_name, role=role)
        provider = (config.reasoning_model_provider or "openai").strip() or "openai"
        key = _credential_key(config, config.reasoning_model_api_key)
        base = _credential_base(config, config.reasoning_model_base_url, key=key)
    budget = _BUDGET_BY_ROLE.get(role) or _BUDGET_BY_ROLE[ROLE_REASONING]
    timeout = max(int(config.llm_timeout_seconds or 0), int(budget["timeout"]))
    max_tokens = max(int(config.llm_max_tokens or 0), int(budget["max_tokens"]))
    return replace(
        config,
        llm_provider=provider,
        llm_model=name,
        llm_api_key=key,
        llm_base_url=base or config.llm_base_url,
        llm_timeout_seconds=timeout,
        llm_max_tokens=max_tokens,
    )


class BrainCompleter:
    """SettingsCompleter bound to one Brain role. Still uses complete_json."""

    def __init__(self, settings: Settings | None = None, *, role: str) -> None:
        self.role = role
        self.settings = layer_settings(settings, role=role)
        self._inner = SettingsCompleter(self.settings)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self._inner.complete_json(system=system, user=user, schema=schema)
        if isinstance(result, dict):
            result = dict(result)
            result["brain_role"] = self.role
        return result


def brain_completers(settings: Settings | None = None) -> tuple[BrainCompleter, BrainCompleter]:
    config = settings or Settings()
    return (
        BrainCompleter(config, role=ROLE_MECHANICAL),
        BrainCompleter(config, role=ROLE_REASONING),
    )


def critic_completer(settings: Settings | None = None) -> BrainCompleter:
    return BrainCompleter(settings, role=ROLE_CRITIC)


def resolve_brain_completers(
    injected: Any | None = None,
    *,
    mechanical: Any | None = None,
    reasoning: Any | None = None,
    settings: Settings | None = None,
) -> tuple[Any, Any]:
    """Tests may inject a single completer for both roles. Production splits layers."""
    if mechanical is not None and reasoning is not None:
        return mechanical, reasoning
    if injected is not None:
        return injected, injected
    return brain_completers(settings)
