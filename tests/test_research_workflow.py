from datetime import datetime, timezone

from stock_pm.research.memory import InMemoryResearchStore
from stock_pm.research.service import ResearchService
from stock_pm.research.types import AgentInput, AgentOutput, FollowUpSpec
from stock_pm.research.workflow import run_follow_up_loop


STAMP = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc).isoformat()


def _runner(task: dict, _inp: AgentInput) -> AgentOutput:
    depth = int(task.get("depth") or 0)
    if depth >= 2:
        return AgentOutput(findings=["leaf"], follow_up_tasks=[], confidence=0.7, agent_name="risk")
    return AgentOutput(
        findings=[f"need depth {depth + 1}"],
        new_evidence=[
            {
                "evidence_type": "transcript",
                "fact": f"follow-up fact at depth {depth}",
                "source": "earnings call",
                "source_time": STAMP,
                "retrieved_at": STAMP,
            }
        ],
        follow_up_tasks=[
            FollowUpSpec(
                title=f"verify depth {depth + 1}",
                task_type="verify_assumption",
                assigned_agents=("risk",),
            )
        ],
        confidence=0.4,
        agent_name="fundamental",
        model="test-model",
        prompt_version="sprint1-test",
    )


def test_follow_up_loop_is_recursive_not_one_pass() -> None:
    svc = ResearchService(InMemoryResearchStore())
    run = svc.start_workflow_run("ZZZZ", trigger="test", max_depth=4, max_tasks=16)
    result = run_follow_up_loop(
        svc,
        ticker="ZZZZ",
        workflow_run_id=run["id"],
        runner=_runner,
        seed_tasks=[{"task_type": "discover_fundamentals", "title": "seed", "assigned_agents": ["fundamental"]}],
        actor="workflow",
    )
    depths = sorted(int(row["depth"]) for row in result["tasks"])
    assert 0 in depths
    assert 2 in depths
    assert result["item_counts"]["processed_tasks"] >= 3
    assert result["workflow_run"]["status"] == "success"
    models = {row.get("model") for row in result["agent_runs"]}
    assert "test-model" in models or any(row.get("output_json", {}).get("model") == "test-model" for row in result["agent_runs"])
    evidence = svc.store.list_evidence("ZZZZ")
    assert evidence
    assert evidence[0]["source"] == "earnings call"


def test_follow_up_loop_stops_at_max_depth() -> None:
    svc = ResearchService(InMemoryResearchStore())
    run = svc.start_workflow_run("ZZZZ", trigger="test", max_depth=1, max_tasks=16)
    result = run_follow_up_loop(
        svc,
        ticker="ZZZZ",
        workflow_run_id=run["id"],
        runner=_runner,
        seed_tasks=[{"task_type": "discover_fundamentals", "title": "seed"}],
    )
    depths = [int(row["depth"]) for row in result["tasks"]]
    assert max(depths) <= 1
    assert result["item_counts"]["dropped_follow_ups"] >= 1
