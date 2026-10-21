# src/harnex/orchestrator/worker_runner.py
"""
Harnex Default Worker Runner Subprocess Entrypoint.
Executes inside the isolated git worktree for a specific subtask.
Communicates status via the Orchestrator Signal Webhook API.
"""
import os
import sys
import time
import httpx


def send_signal(orch_url: str, task_id: str, signal_type: str, message: str = "", diff_patch: str = None, loc: int = 0, tokens: int = 0, credits: float = 0.0):
    url = f"{orch_url}/tasks/{task_id}/signal"
    payload = {
        "task_id": task_id,
        "signal_type": signal_type,
        "worker_pid": os.getpid(),
        "message": message,
        "diff_patch": diff_patch,
        "loc_modified": loc,
        "tokens_used": tokens,
        "credits_used": credits
    }
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        pass


def main():
    task_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HARNEX_TASK_ID")
    if not task_id:
        sys.exit(1)

    orch_url = os.environ.get("HARNEX_ORCHESTRATOR_URL", "http://127.0.0.1:18080/v1/orchestrator")
    assigned_model = os.environ.get("HARNEX_ASSIGNED_MODEL", "gpt-5.6-luna:medium")

    # 1. Report STARTED
    send_signal(orch_url, task_id, "STARTED", f"Worker PID {os.getpid()} started with model {assigned_model}")

    # 2. Simulated work / command execution
    time.sleep(0.05)
    send_signal(orch_url, task_id, "PROGRESS", "Executing instruction step...", loc=5)

    # 3. Report COMPLETED
    send_signal(orch_url, task_id, "COMPLETED", "Subtask successfully completed", loc=10, tokens=350, credits=0.02)
    sys.exit(0)


if __name__ == "__main__":
    main()
