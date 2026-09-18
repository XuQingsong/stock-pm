from __future__ import annotations

from stock_pm.brain.benchmark.events import events_for
from stock_pm.brain.benchmark.freeze import freeze_from_artifact
from stock_pm.brain.benchmark.metrics import empty_human_scores, event_routing_success, score_run
from stock_pm.brain.benchmark.profiles import canonical_model_id, model_profiles, slug_model
from stock_pm.brain.benchmark.runner import run_model_on_pack
from stock_pm.config import Settings
from stock_pm.research.agents.base import SettingsCompleter


def test_events_are_fixed_and_local() -> None:
    for ticker in ("AAPL", "AVGO", "LITE"):
        rows = events_for(ticker)
        assert 8 <= len(rows) <= 10
        assert all(row.get("event_id") and row.get("summary") for row in rows)


def test_artifact_freeze_is_stable() -> None:
    left = freeze_from_artifact("AAPL")
    right = freeze_from_artifact("AAPL")
    assert left is not None and right is not None
    assert left["input_hash"] == right["input_hash"]
    assert left["allowed_evidence_ids"]
    assert left["core_claims"]


def test_two_models_see_identical_frozen_hash() -> None:
    pack = freeze_from_artifact("AVGO")
    assert pack is not None
    assert pack["input_hash"] == freeze_from_artifact("AVGO")["input_hash"]


def test_human_scores_default_null() -> None:
    scores = empty_human_scores()
    assert scores["overall"] is None
    assert all(value is None for value in scores.values())


def test_invalid_ids_and_unsupported_numbers_counted() -> None:
    pack = {
        "allowed_evidence_ids": ["rev_1"],
        "validated_facts": [{"id": "rev_1", "fact": "Management said AI demand remained strong."}],
    }
    metrics = score_run(
        pack=pack,
        drivers={"value_drivers": [{"driver_name": "AI duration", "evidence_ids": ["rev_1", "rev_outside"]}]},
        claims={"core_claims": [{"statement": "AI semiconductors reached $21.7B / +236%.", "supporting_evidence_ids": ["rev_1"]}]},
        events={"events": []},
        counters={"claims": [{"strongest_counter": "capex cut", "what_would_invalidate": "guide cut"}]},
        audits=[{"llm_status": "ok", "input_tokens": 10, "output_tokens": 5, "latency_ms": 3}],
        expected_event_ids=[],
        model="deepseek-chat",
    )
    assert metrics["invalid_evidence_id_count"] >= 1
    assert metrics["unsupported_assertion_count"] >= 1
    assert metrics["human_scores"]["core_claim_quality"] is None
    assert metrics["winner"] if False else metrics["counter_reasoning_count"] == 1


def test_event_routing_requires_transmission() -> None:
    expected = ["e1", "e2"]
    rows = [
        {"event_id": "e1", "direction": "support", "transmission_chain": "Customer 10-Q via AI mix into revenue duration"},
        {"event_id": "e2", "direction": "support", "transmission_chain": "good"},
    ]
    stats = event_routing_success(rows, expected)
    assert stats["routed"] == 2
    assert stats["thin_good_news_bad_news"] >= 1


class ScriptedCompleter:
    def complete_json(self, *, system: str, user: str, schema=None) -> dict:
        if "STEP_ID: driver_discovery" in system:
            payload = {
                "value_drivers": [
                    {
                        "driver_name": "AI demand duration",
                        "description": "Whether AI demand persists.",
                        "why_it_matters": "Binds revenue.",
                        "financial_link": "revenue",
                        "time_horizon": "medium",
                        "current_state": "strong per issuer",
                        "uncertainty": "high",
                        "evidence_ids": ["rev_1"],
                        "missing_evidence": ["customer 10-Q"],
                        "possible_counter_drivers": ["capex slowdown"],
                    }
                ],
                "core_drivers": [{"driver_name": "AI demand duration", "why_selected": "value x uncertainty", "why_not_selected": ""}],
                "not_selected": [],
            }
        elif "STEP_ID: core_claim_test" in system:
            payload = {
                "core_claims": [
                    {
                        "title": "AI demand duration",
                        "statement": "AI semiconductor demand durability remains the binding earnings variable.",
                        "claim_dimension": "growth_duration",
                        "why_core": "highest uncertainty",
                        "supporting_evidence_ids": ["rev_1"],
                        "opposing_evidence_ids": [],
                        "missing_evidence": ["customer 10-Q"],
                    }
                ]
            }
        elif "STEP_ID: event_impact" in system:
            payload = {
                "events": [
                    {
                        "event_id": "avgo_e1",
                        "affected_drivers": ["AI demand duration"],
                        "affected_claims": ["AI demand duration"],
                        "direction": "support",
                        "strength": "medium",
                        "direct_or_indirect": "direct",
                        "transmission_chain": "Issuer 8-K language on AI accelerators supports near-term revenue, not duration.",
                        "short_term_impact": "confirms demand print",
                        "long_term_impact": "does not prove multi-year duration",
                        "financial_metrics_affected": ["revenue"],
                        "base_case_change": "no",
                        "scenario_only": "yes",
                        "confidence": "medium",
                        "evidence_needed_next": "customer capex",
                    }
                ]
            }
        else:
            payload = {
                "claims": [
                    {
                        "claim_id": "bench_1",
                        "title": "AI demand duration",
                        "strongest_support": "issuer AI language",
                        "strongest_counter": "hyperscaler in-house silicon",
                        "competing_hypothesis": "pull-forward",
                        "what_would_invalidate": "guide cut",
                        "most_likely_wrong": "treating one print as duration",
                        "missing_evidence": ["named customer 10-Q"],
                    }
                ]
            }
        return {
            "status": "ok",
            "payload": payload,
            "model": "fake-bench",
            "provider": "test",
            "llm_called": True,
            "llm_status": "ok",
            "input_tokens": 11,
            "output_tokens": 7,
            "latency_ms": 4,
        }


def test_missing_strong_key_does_not_call_llm(monkeypatch) -> None:
    pack = freeze_from_artifact("AAPL")
    assert pack is not None
    called = {"n": 0}

    def boom(_profile):
        called["n"] += 1
        raise AssertionError("completer should not run")

    monkeypatch.setattr("stock_pm.brain.benchmark.runner.completer_for", boom)
    profile = {
        "label": "qwen3.8-max",
        "model": "qwen3.8-max",
        "provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "role": "strong",
        "api_key_present": False,
        "file_aliases": ["qwen3.8-max", "strong"],
        "settings": None,
    }
    out = run_model_on_pack(profile, pack, events_for("AAPL")[:1])
    assert called["n"] == 0
    assert out["searched"] is False
    assert out["input_hash"] == pack["input_hash"]
    assert out["metrics"]["human_scores"]["overall"] is None
    assert "missing" in (out.get("note") or "").lower()


def test_runner_does_not_search_and_binds_ids(monkeypatch) -> None:
    pack = {
        "ticker": "AVGO",
        "input_hash": "abc",
        "snapshot_id": "snap",
        "evidence_set_id": "bes",
        "run_id": "brun",
        "header": {},
        "related_entities": [],
        "core_claims": [{"claim_id": "c1", "title": "AI duration", "statement": "duration is the debate"}],
        "validated_facts": [{"id": "rev_1", "fact": "Management said AI accelerators remained strong."}],
        "allowed_evidence_ids": ["rev_1"],
    }
    profile = {"label": "deepseek", "model": "fake-bench", "provider": "test", "base_url": "", "settings": None, "api_key_present": True}
    monkeypatch.setattr("stock_pm.brain.benchmark.runner.completer_for", lambda _profile: ScriptedCompleter())
    out = run_model_on_pack(profile, pack, events_for("AVGO")[:1])
    assert out["searched"] is False
    assert out["core_claims"][0]["supporting_evidence_ids"] == ["rev_1"]
    assert "21.7" not in (out["core_claims"][0]["statement"] or "")
    assert out["metrics"]["human_scores"]["overall"] is None


def test_slug_and_profiles_keep_production_deepseek(monkeypatch) -> None:
    assert slug_model("ZHIPU/GLM-5.3") == "zhipu-glm-5.3"
    settings = Settings(
        llm_api_key="k",
        llm_model="deepseek-chat",
        llm_base_url="https://api.deepseek.com/v1",
        strong_model_api_key="",
        strong_model_base_url="",
        strong_model_name="",
        benchmark_models="",
    )
    rows = model_profiles(settings)
    assert rows[0]["label"] == "deepseek"
    assert rows[0]["model"] == "deepseek-chat"
    assert all(row["label"] != "strong" for row in rows)


def test_profiles_three_bailian_models() -> None:
    assert canonical_model_id("glm-5.3") == "glm-5.3"
    assert canonical_model_id("ZHIPU/GLM-5.3") == "glm-5.3"
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
    rows = model_profiles(settings)
    assert rows[0]["model"] == "deepseek-chat"
    extra = rows[1:]
    assert [row["model"] for row in extra] == ["qwen3.8-max", "glm-5.3", "kimi-k3"]
    assert extra[0]["file_aliases"][-1] == "strong" or "strong" in extra[0]["file_aliases"]
    assert extra[0]["settings"].llm_model == "qwen3.8-max"
    assert extra[0]["settings"].llm_api_key == "dash-key"
    assert extra[0]["settings"].llm_base_url.endswith("/compatible-mode/v1")
    assert settings.llm_model == "deepseek-chat"
