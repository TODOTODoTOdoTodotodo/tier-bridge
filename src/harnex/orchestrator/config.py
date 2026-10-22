# src/harnex/orchestrator/config.py
import os
import json
from typing import Optional
from pydantic import BaseModel, Field


class OrchestratorConfig(BaseModel):
    """
    Immutable configuration for the Signal-Based Task Orchestrator.
    All fields are configurable via config/orchestrator_config.json and HARNEX_ORCH_* env vars.
    No hardcoding allowed.
    """
    max_subtasks: int = Field(default=20, description="Maximum subtasks allowed per DAG")
    max_dag_depth: int = Field(default=5, description="Maximum depth of the task DAG")
    min_instruction_length: int = Field(default=5, description="Minimum length of task instruction")
    task_timeout_seconds: int = Field(default=600, description="Task execution timeout in seconds")
    worker_heartbeat_interval_seconds: int = Field(default=30, description="Worker heartbeat interval")
    worker_heartbeat_timeout_seconds: int = Field(default=90, description="Zombie worker detection timeout")
    max_patch_size_bytes: int = Field(default=5 * 1024 * 1024, description="Max allowed diff patch size (5MB)")
    worktree_root: str = Field(default="~/.harnex/worktrees", description="Root directory for isolated worktrees")
    worktree_ttl_seconds: int = Field(default=3600, description="Stale worktree retention TTL")
    min_disk_free_bytes: int = Field(default=1024 * 1024 * 1024, description="Minimum free disk space (1GB)")
    git_lock_retry_attempts: int = Field(default=5, description="Max retry attempts on git lock contention")
    git_lock_retry_backoff_base_ms: int = Field(default=200, description="Base backoff ms for git lock retry")
    max_merge_retries: int = Field(default=2, description="Max retry attempts for patch merging")
    failure_policy: str = Field(default="CONTINUE_INDEPENDENT", description="CONTINUE_INDEPENDENT or FAIL_FAST")
    conflict_resolution_tier: str = Field(default="PLATINUM", description="Model tier for resolving 3-way conflicts")
    sse_buffer_size: int = Field(default=1000, description="Max buffer size for SSE event streaming")
    event_history_limit: int = Field(default=200, description="Max event activities retained in ring buffer per DAG")
    memory_injection_enabled: bool = Field(default=True, description="Enable corporate memory pre-fetch for subtasks")
    memory_injection_top_k: int = Field(default=2, description="Top-K corporate memories to prefetch per subtask")


def load_orchestrator_config(config_path: Optional[str] = None) -> OrchestratorConfig:
    """
    Loads OrchestratorConfig with 3-tier precedence:
    1. Environment variables (HARNEX_ORCH_<KEY_UPPER>)
    2. JSON file (config_path or config/orchestrator_config.json)
    3. Built-in defaults in OrchestratorConfig
    """
    file_data = {}
    candidates = []
    if config_path:
        candidates.append(config_path)
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.extend([
        os.path.join(cur_dir, "..", "..", "..", "config", "orchestrator_config.json"),
        os.path.join(cur_dir, "..", "..", "config", "orchestrator_config.json"),
        os.path.expanduser("~/.harnex/live/config/orchestrator_config.json")
    ])

    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    break
            except Exception:
                pass

    fields = OrchestratorConfig.model_fields.keys() if hasattr(OrchestratorConfig, "model_fields") else OrchestratorConfig.__fields__.keys()
    merged = dict(file_data)

    for field_name in fields:
        env_key = f"HARNEX_ORCH_{field_name.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            # Type casting based on field default type
            default_val = getattr(OrchestratorConfig, field_name, None)
            if isinstance(default_val, int):
                try:
                    merged[field_name] = int(env_val)
                except ValueError:
                    pass
            elif isinstance(default_val, float):
                try:
                    merged[field_name] = float(env_val)
                except ValueError:
                    pass
            elif isinstance(default_val, bool):
                merged[field_name] = env_val.lower() in ("true", "1", "yes")
            else:
                merged[field_name] = env_val

    return OrchestratorConfig(**merged)
