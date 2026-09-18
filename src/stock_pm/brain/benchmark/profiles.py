"""Vendor-agnostic model profiles for the Brain Capability Benchmark."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from stock_pm.config import Settings
from stock_pm.research.agents.base import SettingsCompleter

# OpenAI-compatible mainland Model Studio endpoint. Used only when STRONG_MODEL_BASE_URL
# is empty and a DashScope/Bailian key is the credential source. Not a production default.
BAILIAN_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Short names the user may type -> documented Bailian model IDs.
# glm-5.3 is published as ZHIPU/GLM-5.3 (third-party). kimi-k3 is the Alibaba-hosted ID;
# kimi/kimi-k3 is the Moonshot-supplied twin and is left unchanged if requested.
MODEL_ID_ALIASES = {
    "glm-5.3": "ZHIPU/GLM-5.3",
    "glm5.3": "ZHIPU/GLM-5.3",
    "zhipu-glm-5.3": "ZHIPU/GLM-5.3",
}

DEFAULT_BAILIAN_MODELS = ("qwen3.8-max", "ZHIPU/GLM-5.3", "kimi-k3")


def slug_model(name: str) -> str:
    text = str(name or "").strip().lower().replace("/", "-")
    text = re.sub(r"[^a-z0-9.]+", "-", text).strip("-.")
    return text or "model"


def canonical_model_id(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    return MODEL_ID_ALIASES.get(raw.lower(), raw)


def _split_models(raw: str) -> list[str]:
    out: list[str] = []
    for item in str(raw or "").split(","):
        name = canonical_model_id(item)
        if name and name not in out:
            out.append(name)
    return out


def _strong_credentials(settings: Settings) -> tuple[str, str, str]:
    explicit_key = (settings.strong_model_api_key or "").strip()
    dash_key = (settings.dashscope_api_key or "").strip()
    key = explicit_key or dash_key
    base = (settings.strong_model_base_url or "").strip().rstrip("/")
    provider = (settings.strong_model_provider or "openai").strip() or "openai"
    if key and not base and dash_key:
        base = BAILIAN_COMPAT_BASE
    return provider, key, base


def extra_body_for(model: str) -> dict[str, Any] | None:
    """Bailian thinking models reject enable_thinking=false. Leave native mode."""
    lower = str(model or "").lower()
    if "kimi-k3" in lower or "glm-5.3" in lower:
        return None
    return None


def _file_aliases(label: str, model: str, *, also_strong: bool) -> list[str]:
    aliases = [label]
    slug = slug_model(model)
    if slug not in aliases:
        aliases.append(slug)
    if model == "ZHIPU/GLM-5.3" and "glm-5.3" not in aliases:
        aliases.append("glm-5.3")
    if also_strong and "strong" not in aliases:
        aliases.append("strong")
    return aliases


def model_profiles(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Return runnable profiles. First extra model also gets file alias 'strong'."""
    config = settings or Settings()
    profiles: list[dict[str, Any]] = [
        {
            "label": "deepseek",
            "role": "baseline",
            "provider": config.llm_provider or "openai",
            "model": config.llm_model or "deepseek-chat",
            "base_url": (config.llm_base_url or "").rstrip("/"),
            "api_key_present": bool(config.llm_api_key),
            "timeout_seconds": int(config.llm_timeout_seconds or 180),
            "file_aliases": ["deepseek"],
            "settings": config,
        }
    ]
    provider, key, base = _strong_credentials(config)
    names = _split_models(config.benchmark_models)
    strong_name = canonical_model_id(config.strong_model_name)
    if strong_name:
        names = [strong_name] + [item for item in names if item != strong_name]
    if not names and key and base:
        names = list(DEFAULT_BAILIAN_MODELS)
    if not names or not base:
        return profiles
    for index, name in enumerate(names):
        extra = extra_body_for(name)
        strong_settings = replace(
            config,
            llm_provider=provider,
            llm_api_key=key,
            llm_base_url=base,
            llm_model=name,
            llm_timeout_seconds=600,
            llm_max_tokens=32768,
            llm_extra_body=extra,
        )
        label = "strong" if len(names) == 1 else slug_model(name)
        profiles.append(
            {
                "label": label,
                "role": "strong",
                "provider": provider,
                "model": name,
                "base_url": base,
                "api_key_present": bool(key),
                "timeout_seconds": 600,
                "file_aliases": _file_aliases(label, name, also_strong=index == 0),
                "settings": strong_settings,
            }
        )
    return profiles


def completer_for(profile: dict[str, Any]) -> SettingsCompleter:
    return SettingsCompleter(profile.get("settings"))
