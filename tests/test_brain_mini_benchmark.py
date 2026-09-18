from __future__ import annotations

from stock_pm.brain.benchmark.freeze import compact_mini_pack, freeze_from_artifact
from stock_pm.brain.benchmark.mini import ROUND1_EVENT, run_round1_model
from stock_pm.brain.benchmark.profiles import mini_file_label, mini_profiles
from stock_pm.config import Settings


def test_mini_file_labels() -> None:
    assert mini_file_label("glm-5.3") == "glm53"
    assert mini_file_label("kimi-k3") == "kimik3"
    assert mini_file_label("qwen3.8-max") == "qwen38"


def test_compact_pack_is_stable_and_short() -> None:
    raw = freeze_from_artifact("AVGO")
    assert raw is not None
    left = compact_mini_pack(raw)
    right = compact_mini_pack(raw)
    assert left["prompt_input_hash"] == right["prompt_input_hash"]
    assert left["freeze_hash"] == raw["input_hash"]
    assert len(left["evidence"]) <= 8
    assert all(len(str(row.get("fact") or "")) <= 181 for row in left["evidence"])


def test_mini_profiles_four_models() -> None:
    settings = Settings(
        llm_api_key="k",
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com/v1",
        strong_model_provider="openai",
        strong_model_api_key="dash-key",
        strong_model_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        strong_model_name="qwen3.8-max",
        benchmark_models="glm-5.3,qwen3.8-max,kimi-k3",
    )
    rows = mini_profiles(settings)
    labels = [row["file_label"] for row in rows]
    assert "deepseek" in labels
    assert "glm53" in labels
    assert "kimik3" in labels
    assert "qwen38" in labels
    qwen = next(row for row in rows if row["file_label"] == "qwen38")
    assert qwen["settings"].llm_extra_body == {"enable_thinking": False}
    assert qwen["settings"].llm_max_tokens <= 2048
    kimi = next(row for row in rows if row["file_label"] == "kimik3")
    assert kimi["settings"].llm_extra_body == {"temperature": 1}


class MiniCompleter:
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        if "STEP_ID: mini_drivers" in system:
            payload = {
                "value_drivers": [
                    {
                        "driver": "AI demand duration",
                        "why_it_matters": "Binds revenue durability.",
                        "financial_link": "revenue",
                        "uncertainty": "high",
                        "evidence_ids": ["rev_1"],
                    }
                ]
            }
        elif "STEP_ID: mini_claims" in system:
            payload = {
                "core_claims": [
                    {
                        "claim": "AI semiconductor demand duration is the binding earnings variable.",
                        "why_core": "Highest uncertainty versus value.",
                        "strongest_support": "Issuer said AI accelerators remained strong.",
                        "strongest_counter": "Hyperscalers may internalize silicon.",
                        "missing_evidence": "Named customer capex.",
                        "evidence_ids": ["rev_1"],
                    },
                    {
                        "claim": "Margin mix depends on AI vs software mix quality.",
                        "why_core": "Valuation is mix-sensitive.",
                        "strongest_support": "AI described as strong.",
                        "strongest_counter": "Mix not proven.",
                        "missing_evidence": "Segment GM.",
                        "evidence_ids": ["rev_1"],
                    },
                    {
                        "claim": "Customer concentration is a structural risk.",
                        "why_core": "Few hyperscalers.",
                        "strongest_support": "Custom silicon language.",
                        "strongest_counter": "In-house chips.",
                        "missing_evidence": "Customer %.",
                        "evidence_ids": ["rev_1"],
                    },
                ]
            }
        else:
            payload = {
                "event": {
                    "affected_drivers": ["AI demand duration"],
                    "affected_claims": ["AI semiconductor demand duration is the binding earnings variable."],
                    "direction": "oppose",
                    "strength": "medium",
                    "transmission_chain": "Internal ASIC reduces external custom silicon wallet share via hyperscaler substitution.",
                    "short_term_impact": "Does not cancel current AI prints.",
                    "long_term_impact": "Duration and share become scenario-only.",
                    "base_case_change": "no",
                    "scenario_only": "yes",
                    "confidence": "medium",
                }
            }
        return {
            "status": "ok",
            "payload": payload,
            "model": "fake-mini",
            "provider": "test",
            "llm_called": True,
            "llm_status": "ok",
            "input_tokens": 40,
            "output_tokens": 20,
            "latency_ms": 5,
        }


def test_round1_runner_binds_ids_and_does_not_search(monkeypatch) -> None:
    pack = {
        "ticker": "AVGO",
        "snapshot_id": "snap",
        "evidence_set_id": "bes",
        "run_id": "brun",
        "freeze_hash": "abc",
        "prompt_input_hash": "def",
        "related_entities": ["GOOGL", "META"],
        "evidence": [{"id": "rev_1", "fact": "Management said AI accelerators remained strong.", "source": "sec.exhibit"}],
        "allowed_evidence_ids": ["rev_1"],
    }
    monkeypatch.setattr("stock_pm.brain.benchmark.mini.completer_for", lambda _profile: MiniCompleter())
    profile = {"label": "deepseek", "file_label": "deepseek", "model": "deepseek-chat", "api_key_present": True, "settings": None}
    out = run_round1_model(profile, pack)
    assert out["searched"] is False
    assert out["metrics"]["driver_count"] == 1
    assert out["metrics"]["core_claim_count"] == 3
    assert out["core_claims"][0]["evidence_ids"] == ["rev_1"]
    assert out["event"]["direction"] == "oppose"
    assert out["metrics"]["human_scores"]["overall"] is None
    assert ROUND1_EVENT["event_id"] == "avgo_custom_silicon"
