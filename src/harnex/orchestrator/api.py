# src/harnex/orchestrator/api.py
import asyncio
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from harnex.orchestrator.config import load_orchestrator_config
from harnex.orchestrator.models import TaskDAG, SignalMessage, TaskState, validate_dag
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.sandbox import WorktreeSandboxManager
from harnex.orchestrator.worker_pool import SubprocessWorkerPool
from harnex.orchestrator.scheduler import DAGScheduler

orchestrator_router = APIRouter(tags=["orchestrator"])

# Global in-process singletons for orchestrator state
_config = load_orchestrator_config()
_signal_bus = SignalBus(_config)
_sandbox_mgr = WorktreeSandboxManager(base_repo_dir=".", config=_config)
_worker_pool = SubprocessWorkerPool(_config)
_dag_registry: Dict[str, TaskDAG] = {}


def get_orchestrator_summary() -> Dict[str, Any]:
    """ Returns summary statistics for usage_dashboard.html """
    active_count = sum(1 for d in _dag_registry.values() if d.state == TaskState.RUNNING)
    completed_count = sum(1 for d in _dag_registry.values() if d.state == TaskState.COMPLETED)
    failed_count = sum(1 for d in _dag_registry.values() if d.state in (TaskState.FAILED, TaskState.CANCELLED))

    task_list = []
    for d in _dag_registry.values():
        subtask_list = []
        for s in d.subtasks.values():
            subtask_list.append({
                "subtask_id": s.subtask_id,
                "title": s.title,
                "tier": s.assigned_tier,
                "state": s.state.value,
                "worker_pid": s.worker_pid,
                "worktree": s.worktree_path,
                "turns": s.turns_completed,
                "loc": s.loc_modified,
                "credits": s.credits_used,
                "elapsed_seconds": 0
            })
        task_list.append({
            "task_id": d.dag_id,
            "title": d.title,
            "state": d.state.value,
            "created_at": d.created_at,
            "completed_at": d.completed_at,
            "total_subtasks": len(d.subtasks),
            "completed_subtasks": sum(1 for s in d.subtasks.values() if s.state == TaskState.COMPLETED),
            "subtasks": subtask_list
        })

    return {
        "enabled": True,
        "active_tasks_count": active_count,
        "completed_tasks_count": completed_count,
        "failed_tasks_count": failed_count,
        "tasks": task_list
    }


async def _execute_dag_task(dag: TaskDAG) -> None:
    scheduler = DAGScheduler(dag, _signal_bus, _sandbox_mgr, _worker_pool, _config)
    await scheduler.run()


@orchestrator_router.post("/dispatch")
async def dispatch_dag(dag: TaskDAG):
    """
    Submits and dispatches a new TaskDAG.
    Validates circular dependencies, registers DAG, and begins async execution.
    """
    try:
        validate_dag(dag, _config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _dag_registry[dag.dag_id] = dag
    for s in dag.subtasks.values():
        _signal_bus.register_subtask(s)

    asyncio.create_task(_execute_dag_task(dag))

    return {
        "status": "DISPATCHED",
        "dag_id": dag.dag_id,
        "title": dag.title,
        "total_subtasks": len(dag.subtasks)
    }


@orchestrator_router.get("/tasks")
async def list_tasks():
    """ Lists all registered task DAGs and execution status """
    return get_orchestrator_summary()


@orchestrator_router.get("/tasks/{dag_id}")
async def get_task_detail(dag_id: str):
    """ Retrieves detailed state of a specific TaskDAG """
    dag = _dag_registry.get(dag_id)
    if not dag:
        raise HTTPException(status_code=404, detail=f"TaskDAG '{dag_id}' not found.")
    return dag


@orchestrator_router.post("/tasks/{subtask_id}/signal")
async def post_worker_signal(subtask_id: str, signal: SignalMessage):
    """
    Webhook endpoint for worker agents to report status signals (STARTED, PROGRESS, COMPLETED, FAILED).
    """
    signal.task_id = subtask_id
    accepted = await _signal_bus.emit_signal(signal)
    return {"accepted": accepted, "task_id": subtask_id, "state": signal.signal_type.value}


@orchestrator_router.get("/events")
async def sse_events():
    """
    Server-Sent Events (SSE) live stream for dashboard and CLI real-time progress.
    """
    async def event_generator():
        async for signal in _signal_bus.subscribe():
            payload = signal.model_dump_json() if hasattr(signal, "model_dump_json") else signal.json()
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@orchestrator_router.get("/config")
async def get_config():
    """ Returns current non-hardcoded orchestrator configuration """
    return _config.model_dump() if hasattr(_config, "model_dump") else _config.dict()
