# src/harnex/orchestrator/api.py
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from harnex.orchestrator.config import load_orchestrator_config
from harnex.orchestrator.models import TaskDAG, SignalMessage, TaskState, SignalType, ActivityType, validate_dag
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.sandbox import WorktreeSandboxManager
from harnex.orchestrator.worker_pool import SubprocessWorkerPool
from harnex.orchestrator.scheduler import DAGScheduler
import os
from harnex.orchestrator.activity_tracker import ActivityTracker
from harnex.orchestrator.chat_manager import ChatManager
from harnex.orchestrator.workspace_manager import WorkspaceManager

orchestrator_router = APIRouter(tags=["orchestrator"])

_DAG_REGISTRY_PATH = os.path.expanduser("~/.harnex/dag_registry.json")


def _load_dag_registry() -> Dict[str, TaskDAG]:
    reg = {}
    if os.path.exists(_DAG_REGISTRY_PATH):
        try:
            with open(_DAG_REGISTRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for did, ddict in data.items():
                    reg[did] = TaskDAG.model_validate(ddict) if hasattr(TaskDAG, "model_validate") else TaskDAG.parse_obj(ddict)
        except Exception as e:
            print(f"[Warning] Failed to load dag_registry: {e}")
    return reg


def _save_dag_registry() -> None:
    try:
        data = {}
        for did, d in _dag_registry.items():
            data[did] = d.model_dump() if hasattr(d, "model_dump") else d.dict()
        os.makedirs(os.path.dirname(_DAG_REGISTRY_PATH), exist_ok=True)
        with open(_DAG_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Warning] Failed to save dag_registry: {e}")


# Global in-process singletons for orchestrator state
_config = load_orchestrator_config()
_workspace_mgr = WorkspaceManager(_config)
_activity_tracker = ActivityTracker(_config)
_signal_bus = SignalBus(_config, activity_tracker=_activity_tracker)
_dag_registry: Dict[str, TaskDAG] = _load_dag_registry()
_chat_manager = ChatManager(_activity_tracker, _signal_bus, dag_registry=_dag_registry)
_sandbox_mgr = WorktreeSandboxManager(base_repo_dir=".", config=_config)
_worker_pool = SubprocessWorkerPool(_config)


def get_orchestrator_summary() -> Dict[str, Any]:
    """ Returns summary statistics for usage_dashboard.html """
    active_count = sum(1 for d in _dag_registry.values() if d.state == TaskState.RUNNING)
    completed_count = sum(1 for d in _dag_registry.values() if d.state == TaskState.COMPLETED)
    failed_count = sum(1 for d in _dag_registry.values() if d.state in (TaskState.FAILED, TaskState.CANCELLED))

    task_list = []
    for d in _dag_registry.values():
        subtask_list = []
        for s in d.subtasks.values():
            try:
                try:
                    from harnex.credit_interceptor import interceptor
                except ImportError:
                    from src.harnex.credit_interceptor import interceptor
                usage = interceptor.get_session_usage(f"task_{s.subtask_id}", since_timestamp=s.started_at)
                if not usage or usage.get("real_credits", 0) <= 0:
                    usage = interceptor.get_session_usage(f"task_{d.dag_id}_{s.subtask_id}", since_timestamp=s.started_at)
                if usage and usage.get("real_credits", 0) > 0:
                    s.credits_used = usage["real_credits"]
                    s.tokens_used = usage["total_tokens"]
                    if usage.get("turns", 0) > 0:
                        s.turns_completed = usage["turns"]
            except Exception:
                pass

            subtask_list.append({
                "subtask_id": s.subtask_id,
                "title": s.title,
                "tier": s.assigned_tier,
                "state": s.state.value,
                "presence": getattr(s, "presence", "READY"),
                "worker_pid": s.worker_pid,
                "worktree": s.worktree_path,
                "turns": s.turns_completed,
                "loc": s.loc_modified,
                "credits": s.credits_used,
                "elapsed_seconds": 0,
                "injected_memories": getattr(s, "injected_memories", [])
            })
        task_list.append({
            "task_id": d.dag_id,
            "title": d.title,
            "state": d.state.value,
            "target_repo": getattr(d, "target_repo", None),
            "created_at": d.created_at,
            "completed_at": d.completed_at,
            "total_subtasks": len(d.subtasks),
            "completed_subtasks": sum(1 for s in d.subtasks.values() if s.state == TaskState.COMPLETED),
            "subtasks": subtask_list
        })

    return {
        "enabled": True,
        "active_workspace": _workspace_mgr.get_active_workspace(),
        "active_tasks_count": active_count,
        "completed_tasks_count": completed_count,
        "failed_tasks_count": failed_count,
        "tasks": task_list,
        "recent_activities": _activity_tracker.get_recent_global_activities(limit=30)
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
    if not getattr(dag, "target_repo", None):
        dag.target_repo = _workspace_mgr.active_repo

    try:
        validate_dag(dag, _config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _dag_registry[dag.dag_id] = dag
    _save_dag_registry()
    for s in dag.subtasks.values():
        _signal_bus.register_subtask(s)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_name = dag.target_repo.split('/')[-1] if dag.target_repo else "Default"
    print(f"[{now_str}] [task: {dag.dag_id}] ➔ [ORCHESTRATOR: DISPATCH] 목표: \"{dag.title}\" | 서브태스크: {len(dag.subtasks)}개 | 대상: {target_name} ({dag.target_repo})", flush=True)

    asyncio.create_task(_execute_dag_task(dag))

    return {
        "status": "DISPATCHED",
        "dag_id": dag.dag_id,
        "title": dag.title,
        "target_repo": dag.target_repo,
        "total_subtasks": len(dag.subtasks)
    }


@orchestrator_router.get("/fs/browse")
async def browse_filesystem(path: Optional[str] = None):
    """ Lightweight local directory browsing for target repo selection """
    try:
        return _workspace_mgr.browse_directory(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@orchestrator_router.post("/workspace/select")
async def select_workspace_repo(payload: Dict[str, Any]):
    """ Sets active target repo for future dashboard operations """
    repo_path = payload.get("repo_path", "").strip()
    if not repo_path:
        raise HTTPException(status_code=400, detail="repo_path cannot be empty.")
    try:
        return _workspace_mgr.select_workspace(repo_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    for s in dag.subtasks.values():
        try:
            try:
                from harnex.credit_interceptor import interceptor
            except ImportError:
                from src.harnex.credit_interceptor import interceptor
            usage = interceptor.get_session_usage(f"task_{s.subtask_id}", since_timestamp=s.started_at)
            if not usage or usage.get("real_credits", 0) <= 0:
                usage = interceptor.get_session_usage(f"task_{dag.dag_id}_{s.subtask_id}", since_timestamp=s.started_at)
            if usage and usage.get("real_credits", 0) > 0:
                s.credits_used = usage["real_credits"]
                s.tokens_used = usage["total_tokens"]
                if usage.get("turns", 0) > 0:
                    s.turns_completed = usage["turns"]
        except Exception:
            pass
    return dag


@orchestrator_router.get("/tasks/{dag_id}/events")
async def get_dag_events(dag_id: str, limit: int = 50):
    """ Retrieves chronological activity events for a specific TaskDAG """
    return {
        "dag_id": dag_id,
        "activities": _activity_tracker.get_dag_activities(dag_id, limit=limit)
    }


@orchestrator_router.post("/tasks/{dag_id}/chat")
async def post_dag_chat(dag_id: str, payload: Dict[str, Any]):
    """ Injects human intervention message into DAG/SubTask and broadcasts """
    msg = payload.get("message", "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    result = await _chat_manager.handle_user_message(dag_id, msg)
    return result


@orchestrator_router.post("/tasks/{dag_id}/cancel")
async def cancel_dag_task(dag_id: str):
    """
    Cancels an active TaskDAG and terminates all running worker subprocesses.
    """
    dag = _dag_registry.get(dag_id)
    if not dag:
        running_dags = [d for d in _dag_registry.values() if d.state == TaskState.RUNNING]
        if running_dags:
            dag = running_dags[0]
        else:
            return {"status": "NO_ACTIVE_TASK", "message": "중지할 활성 태스크가 없습니다."}

    dag.state = TaskState.CANCELLED
    dag.completed_at = datetime.now(timezone.utc).isoformat()
    _save_dag_registry()

    terminated = []
    for sid, s in dag.subtasks.items():
        if s.state in (TaskState.PENDING, TaskState.READY, TaskState.RUNNING):
            s.state = TaskState.CANCELLED
            s.presence = "CANCELLED"
            await _worker_pool.terminate_worker(sid)
            terminated.append(sid)

    msg = f"🛑 TaskDAG '{dag.dag_id}' 작업이 사용자에 의해 중지되었습니다. (워커 {len(terminated)}개 종료)"
    act = _activity_tracker.record_activity(
        dag_id=dag.dag_id,
        subtask_id="ALL",
        subtask_title="System Operator",
        tier="SYSTEM",
        presence="CANCELLED",
        activity_type=ActivityType.ACTION,
        message=msg
    )

    await _signal_bus.emit_signal(SignalMessage(
        task_id=dag.dag_id,
        signal_type=SignalType.FAILED,
        activity_type=ActivityType.ACTION,
        message=msg
    ))

    return {
        "status": "CANCELLED",
        "dag_id": dag.dag_id,
        "terminated_subtasks": terminated,
        "activity": act
    }


@orchestrator_router.post("/tasks/{subtask_id}/signal")
async def post_worker_signal(subtask_id: str, signal: SignalMessage):
    """
    Webhook endpoint for worker agents to report status signals (STARTED, PROGRESS, COMPLETED, FAILED).
    """
    signal.task_id = subtask_id

    # 실시간 Enterprise 실제 차감 크레딧과 오차 0% 동기화
    try:
        try:
            from harnex.credit_interceptor import interceptor
        except ImportError:
            from src.harnex.credit_interceptor import interceptor
        usage = interceptor.get_session_usage(f"task_{subtask_id}")
        if usage and usage.get("real_credits", 0) > 0:
            signal.credits_used = usage["real_credits"]
            signal.tokens_used = usage["total_tokens"]
            if usage.get("turns", 0) > 0:
                signal.turns_completed = usage["turns"]
    except Exception:
        pass

    accepted = await _signal_bus.emit_signal(signal)
    _save_dag_registry()
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
