"""Recursive follow-up task loop. Not a one-pass agent pipeline."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .runtime import AgentRuntime, agent_name_for_task
from .service import ResearchService
from .types import AGENT_FUNDAMENTAL, AgentInput, AgentOutput, to_plain


Runner = Callable[[dict[str, Any], AgentInput], AgentOutput]


def _config(run: dict[str, Any]) -> tuple[int, int]:
    config = run.get("config_json") or {}
    if isinstance(config, str):
        max_depth, max_tasks = 4, 32
        return max_depth, max_tasks
    return int(config.get("max_depth") or 4), int(config.get("max_tasks") or 32)


def run_follow_up_loop(
    service: ResearchService,
    *,
    ticker: str,
    workflow_run_id: str,
    runner: Runner,
    seed_tasks: list[dict[str, Any]] | None = None,
    actor: str = "workflow",
) -> dict[str, Any]:
    """Drain pending tasks, persist agent output, enqueue follow-ups until empty or capped."""
    run = service.store.get_workflow_run(workflow_run_id)
    if run is None:
        run = service.start_workflow_run(ticker, trigger="test")
        workflow_run_id = run["id"]
    ticker = run["ticker"]
    max_depth, max_tasks = _config(run)
    for spec in seed_tasks or []:
        payload = dict(spec)
        payload["workflow_run_id"] = workflow_run_id
        service.create_task(ticker, payload, actor=actor)

    processed = 0
    dropped_follow_ups = 0
    last_error = None
    while processed < max_tasks:
        task = service.store.next_pending_task(ticker, workflow_run_id)
        if task is None:
            break
        service.store.update_task(task["id"], status="running")
        agent_run = service.store.insert_agent_run(
            {
                "ticker": ticker,
                "workflow_run_id": workflow_run_id,
                "task_id": task["id"],
                "agent_name": (task.get("assigned_agents") or ["search_data"])[0],
                "status": "running",
            }
        )
        agent_input = AgentInput(
            ticker=ticker,
            task=task,
            research_pack=service.get_pack(ticker),
            current_thesis=service.store.get_latest_thesis(ticker),
            assumptions=service.store.list_assumptions(ticker),
            evidence=service.store.list_evidence(ticker),
        )
        try:
            output = runner(task, agent_input)
            persisted = service.persist_agent_output(
                task,
                output,
                agent_run_id=agent_run["id"],
                max_depth=max_depth,
            )
            dropped_follow_ups += int(persisted.get("dropped_follow_ups") or 0)
            service.store.complete_agent_run(
                agent_run["id"],
                status="success",
                output_json={
                    "findings": output.findings,
                    "follow_up_count": len(persisted.get("follow_ups") or []),
                    "missing_data": list(output.missing_data),
                    "model": output.model,
                    "prompt_version": output.prompt_version,
                },
                confidence=output.confidence,
                model=output.model,
                prompt_version=output.prompt_version,
            )
            service.store.update_task(task["id"], status="completed")
            processed += 1
        except Exception as exc:
            last_error = str(exc)
            service.store.complete_agent_run(agent_run["id"], status="failed", error=last_error, output_json={})
            service.store.update_task(task["id"], status="blocked")
            processed += 1

    remaining = [
        row
        for row in service.store.list_tasks(ticker, workflow_run_id)
        if row.get("status") == "pending"
    ]
    status = "success"
    if last_error and processed:
        status = "partial"
    elif last_error:
        status = "failed"
    elif remaining:
        status = "partial"
    counts = {
        "processed_tasks": processed,
        "pending_tasks": len(remaining),
        "dropped_follow_ups": dropped_follow_ups,
        "agent_runs": len(service.store.list_agent_runs(ticker, workflow_run_id)),
    }
    completed = service.store.complete_workflow_run(
        workflow_run_id,
        status=status,
        item_counts=counts,
        error=last_error,
    )
    return {
        "workflow_run": completed,
        "item_counts": counts,
        "tasks": service.store.list_tasks(ticker, workflow_run_id),
        "agent_runs": service.store.list_agent_runs(ticker, workflow_run_id),
    }


def loop_result_plain(result: dict[str, Any]) -> dict[str, Any]:
    return to_plain(result)


def runtime_runner(runtime: AgentRuntime) -> Runner:
    def _run(task: dict[str, Any], payload: AgentInput) -> AgentOutput:
        return runtime.run(agent_name_for_task(task), payload)

    return _run


def run_new_ticker_research(
    service: ResearchService,
    ticker: str,
    *,
    workflow_run_id: str | None = None,
    trigger: str = "api",
    max_depth: int = 4,
    max_tasks: int = 32,
    runtime: AgentRuntime | None = None,
    execute: bool = True,
) -> dict[str, Any]:
    symbol = str(ticker or "").upper()
    service.ensure_issuer(symbol)
    if workflow_run_id:
        run = service.store.get_workflow_run(workflow_run_id)
        if run is None or run.get("ticker") != symbol:
            raise ValueError("workflow run not found")
    else:
        run = service.start_workflow_run(
            symbol,
            workflow_name="new_ticker_research",
            trigger=trigger,
            max_depth=max_depth,
            max_tasks=max_tasks,
        )
        workflow_run_id = run["id"]
    pack = service.build_pack(symbol, workflow_run_id=workflow_run_id)
    existing = service.store.list_tasks(symbol, workflow_run_id)
    if not existing:
        service.create_task(
            symbol,
            {
                "workflow_run_id": workflow_run_id,
                "task_type": "discover_fundamentals",
                "title": "Discover fundamentals, guidance, and management commitments",
                "description": "Analyze the research pack. Extract evidence, propose unverified assumptions, and open follow-up tasks.",
                "source_reason": "template seed",
                "assigned_agents": [AGENT_FUNDAMENTAL],
                "required_data": ["earnings", "guidance", "transcript"],
                "priority": 10,
            },
            actor="workflow",
        )
    if not execute:
        return {
            "workflow_run": service.store.get_workflow_run(workflow_run_id),
            "pack": pack,
            "snapshot": service.research_snapshot(symbol, workflow_run_id),
        }
    resolved_runtime = runtime
    if resolved_runtime is None:
        resolved_runtime = AgentRuntime(completer=service.completer)
    result = run_follow_up_loop(
        service,
        ticker=symbol,
        workflow_run_id=workflow_run_id,
        runner=runtime_runner(resolved_runtime),
        actor="workflow",
    )
    result["pack"] = service.get_pack(symbol)
    result["snapshot"] = service.research_snapshot(symbol, workflow_run_id)
    return result
