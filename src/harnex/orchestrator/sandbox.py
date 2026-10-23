# src/harnex/orchestrator/sandbox.py
import asyncio
import os
import re
import shutil
import time
from typing import Optional

from harnex.orchestrator.config import OrchestratorConfig

SUBTASK_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,64}$")


class WorktreeSandboxManager:
    """
    Manages isolated Git worktrees and branches for worker agents.
    Prevents filesystem write collisions, git index.lock contention, and path traversal attacks.
    """
    def __init__(self, base_repo_dir: str, config: OrchestratorConfig):
        self.base_repo_dir = os.path.abspath(base_repo_dir)
        self.config = config
        self.worktree_root = os.path.abspath(os.path.expanduser(config.worktree_root))
        os.makedirs(self.worktree_root, exist_ok=True)
        self._lock = asyncio.Lock()

    def _validate_subtask_id(self, subtask_id: str) -> str:
        if not SUBTASK_ID_REGEX.match(subtask_id):
            raise ValueError(f"Invalid subtask_id '{subtask_id}'. Must match {SUBTASK_ID_REGEX.pattern} to prevent path injection.")
        return subtask_id

    def get_worktree_path(self, subtask_id: str) -> str:
        self._validate_subtask_id(subtask_id)
        path = os.path.abspath(os.path.join(self.worktree_root, subtask_id))
        if not path.startswith(self.worktree_root):
            raise ValueError(f"Path traversal detected: {path}")
        return path

    async def _run_git(self, args: list, cwd: Optional[str] = None) -> tuple[int, str, str]:
        cmd = ["git"] + args
        work_dir = cwd or self.base_repo_dir
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    def _sync_active_documentation(self, repo_dir: str, worktree_path: str) -> None:
        """
        Safely copies untracked documentation files (.md, docs/) from the active repo
        into the isolated worktree sandbox so workers can reference latest specs.
        """
        try:
            ignore_dirs = {".git", ".harnex-sandboxes", "node_modules", "build", ".gradle", "target", ".venv", "__pycache__", ".idea"}
            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".git")]
                for f in files:
                    if f.endswith(".md") or "/docs/" in root or root.endswith("/docs"):
                        src_file = os.path.join(root, f)
                        rel_path = os.path.relpath(src_file, repo_dir)
                        dest_file = os.path.join(worktree_path, rel_path)
                        if not os.path.exists(dest_file):
                            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                            shutil.copy2(src_file, dest_file)
        except Exception:
            pass

    async def create_sandbox(self, subtask_id: str, base_commit: str = "HEAD", target_repo: Optional[str] = None) -> str:
        """
        Creates an isolated Git worktree for subtask_id at worktree_root/subtask_id
        on a dedicated branch 'task/{subtask_id}'.
        If target_repo is specified and valid, branches from target_repo; otherwise defaults to base_repo_dir.
        Guards against disk exhaustion and git lock contention.
        """
        self._validate_subtask_id(subtask_id)
        worktree_path = self.get_worktree_path(subtask_id)
        repo_dir = os.path.abspath(target_repo) if target_repo and os.path.isdir(target_repo) else self.base_repo_dir

        # 1. Disk space check
        total, used, free = shutil.disk_usage(self.worktree_root)
        if free < self.config.min_disk_free_bytes:
            raise RuntimeError(f"Insufficient disk space in {self.worktree_root} (free: {free}B, required: {self.config.min_disk_free_bytes}B)")

        # 2. Worktree creation with lock & retry
        branch_name = f"task/{subtask_id}"

        async with self._lock:
            if os.path.exists(worktree_path):
                # Clean up preexisting worktree if any (using unlocked internal helper to avoid deadlock)
                await self._cleanup_sandbox_unlocked(subtask_id, target_repo=repo_dir)

            attempts = self.config.git_lock_retry_attempts
            backoff_base = self.config.git_lock_retry_backoff_base_ms / 1000.0

            for attempt in range(attempts):
                # git worktree add <path> -b <branch> <base_commit>
                code, out, err = await self._run_git(["worktree", "add", worktree_path, "-b", branch_name, base_commit], cwd=repo_dir)
                if code == 0:
                    self._sync_active_documentation(repo_dir, worktree_path)
                    return worktree_path

                if "already exists" in err or "이미 있습니다" in err:
                    # branch might exist from previous run, try cleaning up directory and attaching or recreating
                    if os.path.exists(worktree_path):
                        shutil.rmtree(worktree_path, ignore_errors=True)
                    code2, out2, err2 = await self._run_git(["worktree", "add", worktree_path, branch_name], cwd=repo_dir)
                    if code2 == 0:
                        self._sync_active_documentation(repo_dir, worktree_path)
                        return worktree_path

                if "index.lock" in err or "Unable to create" in err:
                    await asyncio.sleep(backoff_base * (2 ** attempt))
                    continue

                raise RuntimeError(f"Failed to create git worktree for '{subtask_id}': {err}")

            raise RuntimeError(f"Failed to create git worktree after {attempts} attempts due to lock contention: {err}")

    async def _cleanup_sandbox_unlocked(self, subtask_id: str, delete_branch: bool = True, target_repo: Optional[str] = None) -> None:
        """
        Internal unlocked cleanup helper to prevent non-reentrant deadlock when called from create_sandbox.
        """
        self._validate_subtask_id(subtask_id)
        worktree_path = self.get_worktree_path(subtask_id)
        branch_name = f"task/{subtask_id}"
        repo_dir = os.path.abspath(target_repo) if target_repo and os.path.isdir(target_repo) else self.base_repo_dir

        if os.path.exists(worktree_path):
            await self._run_git(["worktree", "remove", "--force", worktree_path], cwd=repo_dir)
            if os.path.exists(worktree_path):
                shutil.rmtree(worktree_path, ignore_errors=True)

        await self._run_git(["worktree", "prune"], cwd=repo_dir)

        if delete_branch:
            await self._run_git(["branch", "-D", branch_name], cwd=repo_dir)

    async def cleanup_sandbox(self, subtask_id: str, delete_branch: bool = True, target_repo: Optional[str] = None) -> None:
        """
        Safely removes a worktree and deletes its temporary task branch.
        """
        async with self._lock:
            await self._cleanup_sandbox_unlocked(subtask_id, delete_branch=delete_branch, target_repo=target_repo)

    async def sweep_stale_worktrees(self) -> int:
        """
        Sweeps worktrees that exceed worktree_ttl_seconds.
        Returns the count of swept worktrees.
        """
        now = time.time()
        ttl = self.config.worktree_ttl_seconds
        swept = 0

        async with self._lock:
            if not os.path.exists(self.worktree_root):
                return 0

            for entry in os.listdir(self.worktree_root):
                full_path = os.path.join(self.worktree_root, entry)
                if os.path.isdir(full_path):
                    try:
                        mtime = os.path.getmtime(full_path)
                        if (now - mtime) > ttl:
                            await self._run_git(["worktree", "remove", "--force", full_path])
                            if os.path.exists(full_path):
                                shutil.rmtree(full_path, ignore_errors=True)
                            swept += 1
                    except Exception:
                        pass

            if swept > 0:
                await self._run_git(["worktree", "prune"])

        return swept
