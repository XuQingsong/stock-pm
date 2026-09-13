"""Read machine-readable E1–E10 accept reports for the accept/debug page."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def accept_out_dir() -> Path:
    return Path(os.environ.get("ACCEPT_OUT", "/opt/cursor/artifacts/p0-5b"))


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def load_accept_reports(out_dir: Path | None = None) -> dict[str, Any]:
    root = out_dir or accept_out_dir()
    live = _read_json(root / "live-current.json")
    capability = _read_json(root / "capability-black-box.json")
    source = "accept_report_files" if live or capability else "missing_accept_report"
    return {
        "source": source,
        "provider_health_gate": None if live is None else live.get("provider_health_gate"),
        "live_e1_e10_gate": None if live is None else live.get("live_e1_e10_gate"),
        "capability_e1_e10_gate": None if capability is None else capability.get("capability_e1_e10_gate"),
        "live": live,
        "capability": capability,
        "note": (
            "Gates copied from live-current.json and capability-black-box.json."
            if source == "accept_report_files"
            else "No accept report files yet. Product pages must not invent accept-only gates."
        ),
    }
