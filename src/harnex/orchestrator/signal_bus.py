# src/harnex/orchestrator/signal_bus.py
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, AsyncIterator, Any

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import SignalMessage, SignalType, TaskState, SubTask


class SignalBus:
    """
    In-process Reactive Event Bus and State Transition Manager.
    Manages non-chatty, silent task status signals (STARTED, PROGRESS, HEARTBEAT, COMPLETED, FAILED).
    Ensures state transition invariants and broadcasts signals to SSE subscribers.
    """
    def __init__(self, config: OrchestratorConfig, activity_tracker: Optional[Any] = None):
        self.config = config
        self._subscribers: Set[asyncio.Queue] = set()
        self._subtasks: Dict[str, SubTask] = {}
        self._last_heartbeat: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        if activity_tracker is None:
            try:
                from harnex.orchestrator.activity_tracker import ActivityTracker
            except ImportError:
                from src.harnex.orchestrator.activity_tracker import ActivityTracker
            self.activity_tracker = ActivityTracker(config)
        else:
            self.activity_tracker = activity_tracker

    def register_subtask(self, subtask: SubTask) -> None:
        self._subtasks[subtask.subtask_id] = subtask

    def get_subtask(self, subtask_id: str) -> Optional[SubTask]:
        return self._subtasks.get(subtask_id)

    async def emit_signal(self, signal: SignalMessage) -> bool:
        """
        Emits a signal message, executes state transitions, and notifies subscribers.
        Returns True if signal was accepted and applied, False if rejected (e.g. terminal state).
        """
        async with self._lock:
            subtask = self._subtasks.get(signal.task_id)
            if not subtask:
                # Signal for unregistered task; still broadcast to listeners
                await self._broadcast(signal)
                return True

            # Terminal states guard (Idempotency)
            if subtask.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
                # Silently ignore out-of-order signals for completed/failed tasks
                return False

            now_iso = datetime.now(timezone.utc).isoformat()
            now_epoch = datetime.now(timezone.utc).timestamp()

            # Diff patch size guard (Payload bomb protection)
            if signal.diff_patch and len(signal.diff_patch.encode("utf-8")) > self.config.max_patch_size_bytes:
                signal.signal_type = SignalType.FAILED
                signal.message = f"Diff patch exceeded max_patch_size_bytes ({self.config.max_patch_size_bytes})"
                subtask.state = TaskState.FAILED
                subtask.error_message = signal.message
                subtask.completed_at = now_iso
                await self._broadcast(signal)
                return True

            # State transition logic
            if signal.signal_type == SignalType.STARTED:
                subtask.state = TaskState.RUNNING
                if signal.worker_pid:
                    subtask.worker_pid = signal.worker_pid
                subtask.started_at = now_iso
                self._last_heartbeat[signal.task_id] = now_epoch

            elif signal.signal_type == SignalType.HEARTBEAT:
                self._last_heartbeat[signal.task_id] = now_epoch
                subtask.last_heartbeat = now_iso

            elif signal.signal_type == SignalType.PROGRESS:
                self._last_heartbeat[signal.task_id] = now_epoch
                subtask.last_heartbeat = now_iso
                if signal.loc_modified > 0:
                    subtask.loc_modified = signal.loc_modified
                if signal.tokens_used > 0:
                    subtask.tokens_used = signal.tokens_used
                if signal.credits_used > 0:
                    subtask.credits_used = signal.credits_used

            elif signal.signal_type == SignalType.COMPLETED:
                subtask.state = TaskState.COMPLETED
                subtask.completed_at = now_iso
                if signal.diff_patch:
                    subtask.diff_patch = signal.diff_patch
                if signal.loc_modified > 0:
                    subtask.loc_modified = signal.loc_modified
                if signal.tokens_used > 0:
                    subtask.tokens_used = signal.tokens_used
                if signal.credits_used > 0:
                    subtask.credits_used = signal.credits_used

            elif signal.signal_type == SignalType.FAILED:
                subtask.state = TaskState.FAILED
                subtask.completed_at = now_iso
                subtask.error_message = signal.message

            dag_id = subtask.parent_task_id if subtask else "global"
            act_type_val = signal.activity_type.value if hasattr(signal.activity_type, "value") else str(signal.activity_type)
            if not signal.skip_activity_tracking and act_type_val != "USER_CHAT":
                self.activity_tracker.record_signal_activity(dag_id, subtask, signal)
            await self._broadcast(signal)
            return True

    async def _broadcast(self, signal: SignalMessage) -> None:
        dead_queues = []
        for q in list(self._subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()  # Drop oldest event on buffer overflow (Ring Buffer)
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(signal)
            except Exception:
                dead_queues.append(q)

        for dq in dead_queues:
            self._subscribers.discard(dq)

    async def subscribe(self) -> AsyncIterator[SignalMessage]:
        """
        Subscribes to live signals via an async generator.
        Automatically unregisters upon client disconnection (CancelledError).
        """
        q = asyncio.Queue(maxsize=self.config.sse_buffer_size)
        self._subscribers.add(q)
        try:
            while True:
                signal = await q.get()
                yield signal
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self._subscribers.discard(q)

    def check_zombie_workers(self) -> List[str]:
        """
        Identifies running subtasks whose heartbeat has timed out.
        """
        now = datetime.now(timezone.utc).timestamp()
        timeout = self.config.worker_heartbeat_timeout_seconds
        zombies = []
        for task_id, subtask in self._subtasks.items():
            if subtask.state == TaskState.RUNNING:
                last_hb = self._last_heartbeat.get(task_id, 0)
                if last_hb > 0 and (now - last_hb) > timeout:
                    zombies.append(task_id)
        return zombies
