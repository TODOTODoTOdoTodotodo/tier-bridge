# src/harnex/orchestrator/barrier.py
import asyncio
import os
from typing import Optional, Tuple

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import SubTask


class JoinBarrier:
    """
    Manages final merging of subtask patches into the main branch.
    Checks dirty working tree, applies 3-way git patches, and guards against merge contamination.
    """
    def __init__(self, repo_root: str, config: OrchestratorConfig):
        self.repo_root = os.path.abspath(repo_root)
        self.config = config
        self._lock = asyncio.Lock()

    async def _run_git(self, args: list) -> Tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=self.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    async def check_clean_working_tree(self) -> bool:
        code, out, err = await self._run_git(["status", "--porcelain"])
        return code == 0 and len(out.strip()) == 0

    async def apply_subtask_patch(self, subtask: SubTask) -> bool:
        """
        Safely applies the subtask's diff_patch to the base repository.
        Returns True on success, False on failure.
        """
        if not subtask.diff_patch or not subtask.diff_patch.strip():
            # No changes to apply
            return True

        async with self._lock:
            # 1. Guard: Check dirty working tree
            is_clean = await self.check_clean_working_tree()
            if not is_clean:
                # Create temporary auto-stash to protect user's uncommitted modifications
                stash_code, _, _ = await self._run_git(["stash", "create", "harnex-auto-stash"])
                if stash_code != 0:
                    return False

            # 2. Write patch to temporary file
            patch_file = os.path.join(self.repo_root, f".harnex_patch_{subtask.subtask_id}.diff")
            try:
                with open(patch_file, "w", encoding="utf-8") as f:
                    f.write(subtask.diff_patch)

                # 3. Try git apply --3way
                apply_code, out, err = await self._run_git(["apply", "--3way", patch_file])
                if apply_code == 0:
                    # Successfully applied! Commit patch
                    commit_msg = f"feat({subtask.subtask_id}): {subtask.title}\n\nAuto-merged by Harnex Orchestrator (Worker PID: {subtask.worker_pid})"
                    await self._run_git(["commit", "-am", commit_msg])
                    return True

                # 4. Conflict occurred
                # Attempt rollback to clean state
                await self._run_git(["reset", "--hard", "HEAD"])
                return False

            finally:
                if os.path.exists(patch_file):
                    try:
                        os.remove(patch_file)
                    except OSError:
                        pass
