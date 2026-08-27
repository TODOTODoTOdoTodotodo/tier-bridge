# src/tierbridge/git_sync_checker.py
import os
import time
import subprocess
import logging
from datetime import datetime

logger = logging.getLogger("tierbridge.git_sync")

_cached_status = None
_last_check_time = 0
CACHE_TTL_SECONDS = 180  # 3분 캐시 유지


def get_git_sync_status(force: bool = False, repo_dir: str = None) -> dict:
    """
    원격 Git 저장소(origin)와의 동기화 상태(pull 필요 여부, 커밋 수 등)를 검사하여 반환합니다.
    서버 부하 및 네트워크 지연을 방지하기 위해 결과를 메모리에 캐싱(TTL: 3분)합니다.
    """
    global _cached_status, _last_check_time

    current_time = time.time()
    if not force and _cached_status is not None and (current_time - _last_check_time < CACHE_TTL_SECONDS):
        return _cached_status

    target_dir = repo_dir or os.getcwd()

    result = {
        "is_git": False,
        "current_branch": "unknown",
        "needs_pull": False,
        "behind_count": 0,
        "ahead_count": 0,
        "pending_commits": [],
        "last_checked": datetime.now().strftime("%H:%M:%S"),
        "error": None
    }

    try:
        # Git 저장소 루트 확인
        root_check = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=target_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2
        )
        if root_check.returncode != 0:
            result["error"] = "Not a git repository"
            _cached_status = result
            _last_check_time = current_time
            return result

        git_root = root_check.stdout.strip()
        result["is_git"] = True

        # 현재 브랜치 확인
        branch_check = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=git_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2
        )
        branch = branch_check.stdout.strip() if branch_check.returncode == 0 else "HEAD"
        result["current_branch"] = branch

        if branch and branch != "HEAD":
            # 원격 메타데이터 비동기 페치 (타임아웃 3.5초)
            try:
                subprocess.run(
                    ["git", "fetch", "--quiet", "origin", branch],
                    cwd=git_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=3.5
                )
            except subprocess.TimeoutExpired:
                logger.warning("Git fetch timed out (>3.5s). Using local remote tracking ref.")

            # 로컬이 원격보다 뒤처진 커밋 수 (behind)
            behind_check = subprocess.run(
                ["git", "rev-list", "HEAD..@{u}", "--count"],
                cwd=git_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            if behind_check.returncode == 0:
                behind_count = int(behind_check.stdout.strip() or 0)
                result["behind_count"] = behind_count
                result["needs_pull"] = behind_count > 0

                if behind_count > 0:
                    # 대기 중인 커밋 요약 (최대 5개)
                    log_check = subprocess.run(
                        ["git", "log", "-n", "5", "HEAD..@{u}", "--oneline"],
                        cwd=git_root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2
                    )
                    if log_check.returncode == 0 and log_check.stdout.strip():
                        result["pending_commits"] = [
                            line.strip() for line in log_check.stdout.strip().split("\n") if line.strip()
                        ]

            # 로컬이 원격보다 앞선 커밋 수 (ahead)
            ahead_check = subprocess.run(
                ["git", "rev-list", "@{u}..HEAD", "--count"],
                cwd=git_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            if ahead_check.returncode == 0:
                result["ahead_count"] = int(ahead_check.stdout.strip() or 0)

    except Exception as e:
        logger.warning(f"Failed to check git sync status: {e}")
        result["error"] = str(e)

    _cached_status = result
    _last_check_time = current_time
    return result
