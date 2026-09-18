"""Five cognitive layers. Lower layers may change faster than higher ones."""

from __future__ import annotations

from typing import Any

from .types import COGNITIVE_LAYERS, LAYER_RANK, OBJECT_LAYER


def object_layer(object_type: str | None) -> str:
    key = str(object_type or "").strip().lower()
    return OBJECT_LAYER.get(key, "observation")


def layer_rank(layer_or_type: str | None) -> int:
    text = str(layer_or_type or "").strip().lower()
    if text in LAYER_RANK:
        return LAYER_RANK[text]
    return LAYER_RANK[object_layer(text)]


def slower_than(target_type: str | None, source_type: str | None) -> bool:
    return layer_rank(target_type) > layer_rank(source_type)


def classify_brain_object(row: dict[str, Any] | None) -> dict[str, Any]:
    item = row or {}
    object_type = str(item.get("object_type") or item.get("kind") or "")
    layer = object_layer(object_type)
    return {
        "object_type": object_type,
        "layer": layer,
        "rank": LAYER_RANK[layer],
        "layers": list(COGNITIVE_LAYERS),
    }
