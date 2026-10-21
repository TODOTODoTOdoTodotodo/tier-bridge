# src/harnex/orchestrator/scheduler.py
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import TaskDAG, SubTask, TaskState, SignalType, validate_dag
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.sandbox import WorktreeSandboxManager
from harnex.orchestrator.worker_pool import SubprocessWorkerPool


class DAGScheduler:
    """
    Topological Sort Asynchronous DAG Scheduler.
    Manages dependency resolution, parallel dispatch, and cascade failure isolation.
    """
    def __init__(
        self,
        dag: TaskDAG,
        signal_bus: SignalBus,
        sandbox_mgr: WorktreeSandboxManager,
        worker_pool: SubprocessWorkerPool,
        config: OrchestratorConfig
    ):
        self.dag = dag
        self.signal_bus = signal_bus
        self.sandbox_mgr = sandbox_mgr
        self.worker_pool = worker_pool
        self.config = config

        self._in_degree: Dict[str, int] = {}
        self._adj_list: Dict[str, List[str]] = {}
        self._reverse_adj: Dict[str, List[str]] = {}
        self._lock = asyncio.Lock()
        self._done_event = asyncio.Event()

    def _init_graph(self) -> None:
        validate_dag(self.dag, self.config)
        for sid, task in self.dag.subtasks.items():
            self.signal_bus.register_subtask(task)
            self._in_degree[sid] = len(task.dependencies)
            self._adj_list[sid] = []
            self._reverse_adj[sid] = list(task.dependencies)

        for sid, task in self.dag.subtasks.items():
            for dep_id in task.dependencies:
                self._adj_list[dep_id].append(sid)

    async def run(self, custom_worker_cmd: Optional[List[str]] = None) -> TaskState:
        """
        Executes the DAG to completion.
        Returns the final TaskState of the DAG (COMPLETED or FAILED).
        """
        self._init_graph()
        self.dag.state = TaskState.RUNNING

        # 1. Start event listener loop
        listener_task = asyncio.create_task(self._listen_signals())

        # 2. Dispatch all initial tasks with in_degree == 0
        initial_tasks = [sid for sid, deg in self._in_degree.items() if deg == 0]
        for sid in initial_tasks:
            asyncio.create_task(self._dispatch_subtask(sid, custom_worker_cmd))

        # 3. Wait until all tasks reach terminal state
        await self._done_event.wait()
        listener_task.cancel()

        self.dag.completed_at = datetime.now(timezone.utc).isoformat()
        all_completed = all(t.state == TaskState.COMPLETED for t in self.dag.subtasks.values())
        self.dag.state = TaskState.COMPLETED if all_completed else TaskState.FAILED
        return self.dag.state

    async def _dispatch_subtask(self, subtask_id: str, custom_cmd: Optional[List[str]]) -> None:
        subtask = self.dag.subtasks[subtask_id]
        async with self._lock:
            if subtask.state != TaskState.PENDING:
                return
            subtask.state = TaskState.READY

        try:
            # Create isolated Git worktree sandbox
            worktree_path = await self.sandbox_mgr.create_sandbox(subtask_id)
            # Spawn worker subprocess inside sandbox
            await self.worker_pool.spawn_worker(
                subtask=subtask,
                worktree_path=worktree_path,
                cmd=custom_cmd,
                signal_bus=self.signal_bus
            )
        except Exception as e:
            from harnex.orchestrator.models import SignalMessage
            await self.signal_bus.emit_signal(SignalMessage(
                task_id=subtask_id,
                signal_type=SignalType.FAILED,
                message=f"Dispatch failed: {str(e)}"
            ))

    async def _listen_signals(self) -> None:
        """
        Consumes signals from signal_bus and triggers dependent task execution.
        """
        async for signal in self.signal_bus.subscribe():
            if signal.task_id not in self.dag.subtasks:
                continue

            if signal.signal_type == SignalType.COMPLETED:
                await self._on_subtask_completed(signal.task_id)
            elif signal.signal_type == SignalType.FAILED:
                await self._on_subtask_failed(signal.task_id)

    async def _on_subtask_completed(self, subtask_id: str) -> None:
        async with self._lock:
            # Unblock downstream dependents
            for neighbor in self._adj_list.get(subtask_id, []):
                self._in_degree[neighbor] -= 1
                if self._in_degree[neighbor] == 0:
                    asyncio.create_task(self._dispatch_subtask(neighbor, None))

            self._check_dag_completion()

    async def _on_subtask_failed(self, subtask_id: str) -> None:
        async with self._lock:
            if self.config.failure_policy == "FAIL_FAST":
                # Cancel all remaining tasks immediately
                for sid, t in self.dag.subtasks.items():
                    if t.state in (TaskState.PENDING, TaskState.READY, TaskState.RUNNING):
                        t.state = TaskState.CANCELLED
                        await self.worker_pool.terminate_worker(sid)
            else:
                # CONTINUE_INDEPENDENT: cascade cancel only downstream dependents
                dependents = self._get_transitive_dependents(subtask_id)
                for dep_id in dependents:
                    dep_task = self.dag.subtasks.get(dep_id)
                    if dep_task and dep_task.state in (TaskState.PENDING, TaskState.READY):
                        dep_task.state = TaskState.CANCELLED

            self._check_dag_completion()

    def _get_transitive_dependents(self, root_id: str) -> Set[str]:
        visited: Set[str] = set()
        queue = [root_id]
        while queue:
            curr = queue.pop(0)
            for neighbor in self._adj_list.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return visited

    def _check_dag_completion(self) -> None:
        terminal_states = (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)
        all_terminal = all(t.state in terminal_states for t in self.dag.subtasks.values())
        if all_terminal:
            self._done_event.set()
