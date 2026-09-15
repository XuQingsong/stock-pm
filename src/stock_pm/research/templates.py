from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from .classify import TEMPLATE_GENERIC


def _templates_dir() -> Path:
    return Path(str(files("stock_pm").joinpath("research/templates")))


@lru_cache(maxsize=8)
def load_template(template_id: str | None) -> dict[str, Any]:
    name = str(template_id or TEMPLATE_GENERIC).strip() or TEMPLATE_GENERIC
    path = _templates_dir() / f"{name}.json"
    if not path.is_file():
        path = _templates_dir() / f"{TEMPLATE_GENERIC}.json"
    if not path.is_file():
        return {"id": TEMPLATE_GENERIC, "question_axes": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_prompt(name: str) -> str:
    path = Path(str(files("stock_pm").joinpath("research/prompts"))) / name
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def verification_seeds(template_id: str | None) -> list[dict[str, Any]]:
    template = load_template(template_id)
    return [dict(item) for item in (template.get("verification_seeds") or []) if isinstance(item, dict)]
