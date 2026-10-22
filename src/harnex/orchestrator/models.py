# src/harnex/orchestrator/models.py
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from harnex.orchestrator.config import OrchestratorConfig


class TaskState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SignalType(str, Enum):
    STARTED = "STARTED"
    PROGRESS = "PROGRESS"
    HEARTBEAT = "HEARTBEAT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActivityType(str, Enum):
    LOG = "LOG"
    THOUGHT = "THOUGHT"
    MEMORY = "MEMORY"
    ACTION = "ACTION"
    READY = "READY"
    USER_CHAT = "USER_CHAT"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SignalMessage(BaseModel):
    task_id: str
    signal_type: SignalType
    activity_type: ActivityType = ActivityType.LOG
    worker_pid: Optional[int] = None
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = ""
    diff_patch: Optional[str] = None
    loc_modified: int = 0
    tokens_used: int = 0
    credits_used: float = 0.0
    injected_memory_titles: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=utc_now_iso)


class SubTask(BaseModel):
    subtask_id: str
    parent_task_id: str
    title: str
    instruction: str
    dependencies: List[str] = Field(default_factory=list)
    assigned_tier: str = "SILVER"
    state: TaskState = TaskState.PENDING
    presence: str = "READY"
    worker_pid: Optional[int] = None
    worktree_path: Optional[str] = None
    turns_completed: int = 0
    diff_patch: Optional[str] = None
    loc_modified: int = 0
    tokens_used: int = 0
    credits_used: float = 0.0
    injected_memories: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    last_heartbeat: Optional[str] = None


class TaskDAG(BaseModel):
    dag_id: str
    title: str
    subtasks: Dict[str, SubTask] = Field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    created_at: str = Field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)


def validate_dag(dag: TaskDAG, config: OrchestratorConfig) -> None:
    """
    Validates the structure, size, and referential integrity of a TaskDAG.
    Uses Kahn's algorithm for cycle detection and computes maximum DAG depth.
    Raises ValueError on any violation.
    """
    subtasks = dag.subtasks
    if len(subtasks) == 0:
        raise ValueError("TaskDAG must contain at least 1 subtask.")

    if len(subtasks) > config.max_subtasks:
        raise ValueError(f"Exceeded max_subtasks ({len(subtasks)} > {config.max_subtasks}).")

    in_degree: Dict[str, int] = {sid: 0 for sid in subtasks}
    adj_list: Dict[str, List[str]] = {sid: [] for sid in subtasks}

    for sid, task in subtasks.items():
        if len(task.instruction.strip()) < config.min_instruction_length:
            raise ValueError(f"Subtask '{sid}' instruction is too short (< {config.min_instruction_length} chars).")

        for dep_id in task.dependencies:
            if dep_id not in subtasks:
                raise ValueError(f"Subtask '{sid}' has dangling dependency '{dep_id}'.")
            if dep_id == sid:
                raise ValueError(f"Subtask '{sid}' cannot depend on itself.")
            adj_list[dep_id].append(sid)
            in_degree[sid] += 1

    # Kahn's Algorithm
    zero_in_degree = [sid for sid, deg in in_degree.items() if deg == 0]
    visited_count = 0
    depth_map: Dict[str, int] = {sid: 1 for sid in zero_in_degree}

    queue = list(zero_in_degree)
    while queue:
        curr = queue.pop(0)
        visited_count += 1
        curr_depth = depth_map[curr]

        for neighbor in adj_list[curr]:
            depth_map[neighbor] = max(depth_map.get(neighbor, 1), curr_depth + 1)
            if depth_map[neighbor] > config.max_dag_depth:
                raise ValueError(f"DAG depth exceeded limit ({depth_map[neighbor]} > {config.max_dag_depth}).")

            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(subtasks):
        unresolved = [sid for sid, deg in in_degree.items() if deg > 0]
        raise ValueError(f"Circular dependency detected in DAG involving subtasks: {unresolved}")
