"""Map sector/themes to a research template. Never branch on ticker."""

from __future__ import annotations

from typing import Any


TEMPLATE_GENERIC = "generic_company"
TEMPLATE_SEMICONDUCTOR = "semiconductor"
TEMPLATE_ENERGY = "energy"


def classify_template(
    *,
    sector: str | None = None,
    themes: list[str] | tuple[str, ...] | None = None,
    asset_class: str | None = None,
) -> str:
    if str(asset_class or "").lower() == "etf":
        return TEMPLATE_GENERIC
    theme_set = {str(item).lower() for item in (themes or [])}
    sector_text = str(sector or "").lower()
    if "semis" in theme_set or "半导体" in sector_text or "semiconductor" in sector_text:
        return TEMPLATE_SEMICONDUCTOR
    if (
        "energy" in theme_set
        or "oil_producer" in theme_set
        or "能源" in sector_text
        or "energy" in sector_text
    ):
        return TEMPLATE_ENERGY
    return TEMPLATE_GENERIC


def classify_from_issuer(row: dict[str, Any] | None) -> str:
    payload = row or {}
    return classify_template(
        sector=payload.get("sector"),
        themes=payload.get("themes") or payload.get("aliases"),
        asset_class=payload.get("asset_class"),
    )
