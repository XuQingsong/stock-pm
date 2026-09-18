"""Five cognitive layers. Lower layers may change faster than higher ones."""

from __future__ import annotations

from typing import Any

from .types import COGNITIVE_LAYERS, FAST_LAYERS, LAYER_RANK, LAYER_SPEED, OBJECT_LAYER


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


def layer_speed(layer_or_type: str | None) -> str:
    text = str(layer_or_type or "").strip().lower()
    if text in LAYER_SPEED:
        return LAYER_SPEED[text]
    return LAYER_SPEED[object_layer(text)]


def is_fast_layer(layer_or_type: str | None) -> bool:
    text = str(layer_or_type or "").strip().lower()
    layer = text if text in LAYER_SPEED else object_layer(text)
    return layer in FAST_LAYERS


def classify_brain_object(row: dict[str, Any] | None) -> dict[str, Any]:
    item = row or {}
    object_type = str(item.get("object_type") or item.get("kind") or "")
    layer = object_layer(object_type)
    return {
        "object_type": object_type,
        "layer": layer,
        "rank": LAYER_RANK[layer],
        "speed": LAYER_SPEED[layer],
        "layers": list(COGNITIVE_LAYERS),
    }
