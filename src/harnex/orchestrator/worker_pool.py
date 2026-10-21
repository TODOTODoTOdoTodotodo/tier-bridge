# src/harnex/orchestrator/worker_pool.py
import asyncio
import os
import signal
from typing import Dict, Optional, List

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import SubTask, SignalMessage, SignalType
from harnex.orchestrator.signal_bus import SignalBus

TIER_MODEL_MAPPING = {
    "BRONZE": "gpt-5.6-luna:low",
    "SILVER": "gpt-5.6-luna:medium",
    "GOLD": "gpt-5.6-terra:medium",
    "PLATINUM": "gpt-5.6-terra:high",
    "DIAMOND": "gpt-5.6-terra:extra_high",
    "CHALLENGER": "gpt-6.1-sol:extra_high",
}


class SubprocessWorkerPool:
    """
    Manages worker execution as isolated OS subprocesses (not threads).
    Ensures that each worker has independent PID, cwd (isolated worktree), and environment.
    Watches worker lifecycle, detects crashes, and handles graceful/forceful termination.
    """
    def __init__(self, config: OrchestratorConfig, proxy_port: int = 18080):
        self.config = config
        self.proxy_port = proxy_port
        self._active_processes: Dict[str, asyncio.subprocess.Process] = {}

    def get_model_for_tier(self, tier: str) -> str:
        return TIER_MODEL_MAPPING.get(tier.upper(), "gpt-5.6-luna:medium")

    def build_worker_env(self, subtask: SubTask) -> Dict[str, str]:
        env = dict(os.environ)
        env["OLLAMA_HOST"] = f"http://127.0.0.1:{self.proxy_port}"
        env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{self.proxy_port}/v1"
        env["CODEX_API_BASE"] = f"http://127.0.0.1:{self.proxy_port}/v1"
        env["HARNEX_TASK_ID"] = subtask.subtask_id
        env["HARNEX_PARENT_DAG_ID"] = subtask.parent_task_id
        env["HARNEX_ORCHESTRATOR_URL"] = f"http://127.0.0.1:{self.proxy_port}/v1/orchestrator"
        env["HARNEX_ASSIGNED_MODEL"] = self.get_model_for_tier(subtask.assigned_tier)
        return env

    async def spawn_worker(
        self,
        subtask: SubTask,
        worktree_path: str,
        cmd: Optional[List[str]] = None,
        signal_bus: Optional[SignalBus] = None
    ) -> asyncio.subprocess.Process:
        """
        Spawns a worker OS subprocess inside worktree_path with isolated env.
        """
        env = self.build_worker_env(subtask)

        # Default worker command if not provided: run python agent worker module
        if not cmd:
            cmd = ["python3", "-m", "harnex.orchestrator.worker_runner", subtask.subtask_id]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=worktree_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        self._active_processes[subtask.subtask_id] = proc
        subtask.worker_pid = proc.pid
        subtask.worktree_path = worktree_path

        if signal_bus:
            # Emit STARTED signal
            await signal_bus.emit_signal(SignalMessage(
                task_id=subtask.subtask_id,
                signal_type=SignalType.STARTED,
                worker_pid=proc.pid,
                message=f"Worker spawned in {worktree_path}"
            ))
            # Start background lifecycle monitor
            asyncio.create_task(self._monitor_worker(subtask.subtask_id, proc, signal_bus))

        return proc

    async def _monitor_worker(self, subtask_id: str, proc: asyncio.subprocess.Process, signal_bus: SignalBus) -> None:
        """
        Monitors worker process completion.
        If process crashes without sending terminal signal, emits SIGNAL_FAILED.
        """
        stdout, stderr = await proc.communicate()
        self._active_processes.pop(subtask_id, None)

        subtask = signal_bus.get_subtask(subtask_id)
        if subtask and subtask.state not in ("COMPLETED", "FAILED", "CANCELLED"):
            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace")[-500:] if stderr else f"Exit code {proc.returncode}"
                await signal_bus.emit_signal(SignalMessage(
                    task_id=subtask_id,
                    signal_type=SignalType.FAILED,
                    worker_pid=proc.pid,
                    message=f"Worker process crashed (code {proc.returncode}): {err_text}"
                ))

    async def terminate_worker(self, subtask_id: str, timeout_seconds: float = 3.0) -> None:
        """
        Gracefully terminates (SIGTERM) then forcibly kills (SIGKILL) a worker process.
        """
        proc = self._active_processes.pop(subtask_id, None)
        if not proc or proc.returncode is not None:
            return

        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

    async def terminate_all(self) -> None:
        for sid in list(self._active_processes.keys()):
            await self.terminate_worker(sid)
