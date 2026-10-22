# src/harnex/orchestrator/workspace_manager.py
"""
WorkspaceManager: 작업 대상 레포지토리 및 로컬 파일시스템 탐색 전담 관리자
단일 책임 원칙(SRP)에 따라 대상 프로젝트 경로 관리, Git 저장소 탐색, 최근 작업 디렉토리 영속화를 전담합니다.
"""
import json
import os
from typing import Dict, Any, List, Optional

from harnex.orchestrator.config import OrchestratorConfig


class WorkspaceManager:
    """
    대시보드 및 멀티에이전트가 작업할 타겟 레포지토리 관리 및 파일시스템 디렉토리 브라우저 서비스.
    """
    def __init__(self, config: OrchestratorConfig, base_dir: Optional[str] = None):
        self.config = config
        self.base_dir = os.path.abspath(base_dir or os.getcwd())
        self.config_dir = os.path.abspath(os.path.expanduser("~/.harnex"))
        os.makedirs(self.config_dir, exist_ok=True)
        self.workspaces_file = os.path.join(self.config_dir, "workspaces.json")
        self._load_state()

    def _load_state(self) -> None:
        self.active_repo = self.base_dir
        self.recent_repositories: List[str] = [self.base_dir]
        if os.path.exists(self.workspaces_file):
            try:
                with open(self.workspaces_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    saved_active = data.get("active_repo")
                    if saved_active and os.path.isdir(saved_active):
                        self.active_repo = os.path.abspath(saved_active)
                    recents = data.get("recent_repositories", [])
                    valid_recents = [os.path.abspath(p) for p in recents if os.path.isdir(p)]
                    if self.active_repo not in valid_recents:
                        valid_recents.insert(0, self.active_repo)
                    self.recent_repositories = valid_recents[:5]
            except Exception:
                pass

    def _save_state(self) -> None:
        try:
            with open(self.workspaces_file, "w", encoding="utf-8") as f:
                json.dump({
                    "active_repo": self.active_repo,
                    "recent_repositories": self.recent_repositories
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    @staticmethod
    def get_git_branch(path: str) -> Optional[str]:
        """
        초경량(<1ms) 방식으로 디렉토리의 Git 브랜치명을 확인합니다.
        서브프로세스를 띄우지 않고 .git/HEAD 파일을 직접 파싱합니다.
        """
        git_dir = os.path.join(path, ".git")
        if not os.path.exists(git_dir):
            return None

        # .git이 파일인 경우 (git worktree인 경우)
        if os.path.isfile(git_dir):
            try:
                with open(git_dir, "r", encoding="utf-8") as f:
                    line = f.readline().strip()
                    if line.startswith("gitdir:"):
                        real_git_dir = line.split(":", 1)[1].strip()
                        head_path = os.path.join(real_git_dir, "HEAD")
                        if os.path.exists(head_path):
                            with open(head_path, "r", encoding="utf-8") as hf:
                                content = hf.read().strip()
                                if content.startswith("ref: refs/heads/"):
                                    return content[16:]
                                return content[:8]
            except Exception:
                return "worktree"
            return "worktree"

        # .git이 디렉토리인 일반 Git 저장소
        head_path = os.path.join(git_dir, "HEAD")
        if os.path.isfile(head_path):
            try:
                with open(head_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content.startswith("ref: refs/heads/"):
                        return content[16:]
                    return content[:8]
            except Exception:
                return "HEAD"
        return "git"

    def get_active_workspace(self) -> Dict[str, Any]:
        """
        현재 선택된 활성 타겟 레포지토리 정보 반환
        """
        branch = self.get_git_branch(self.active_repo)
        return {
            "path": self.active_repo,
            "name": os.path.basename(self.active_repo) or self.active_repo,
            "is_git_repo": branch is not None,
            "git_branch": branch,
            "recent_repositories": self.recent_repositories
        }

    def select_workspace(self, repo_path: str) -> Dict[str, Any]:
        """
        타겟 레포지토리를 변경하고 최근 목록에 등록합니다.
        """
        resolved = os.path.abspath(os.path.expanduser(repo_path))
        if not os.path.isdir(resolved):
            raise ValueError(f"디렉토리가 존재하지 않습니다: '{repo_path}'")

        branch = self.get_git_branch(resolved)
        self.active_repo = resolved

        # 최근 목록 갱신 (최상단 이동, 최대 5개)
        if resolved in self.recent_repositories:
            self.recent_repositories.remove(resolved)
        self.recent_repositories.insert(0, resolved)
        self.recent_repositories = self.recent_repositories[:5]

        self._save_state()
        return {
            "status": "SELECTED",
            "active_repo": self.active_repo,
            "name": os.path.basename(self.active_repo) or self.active_repo,
            "is_git_repo": branch is not None,
            "git_branch": branch,
            "recent_repositories": self.recent_repositories
        }

    def browse_directory(self, target_path: Optional[str] = None) -> Dict[str, Any]:
        """
        로컬 디렉토리를 경량 탐색하여 하위 폴더 및 Git 저장소 목록을 반환합니다.
        """
        if not target_path or not target_path.strip():
            curr = self.active_repo
        else:
            curr = os.path.abspath(os.path.expanduser(target_path.strip()))

        if not os.path.isdir(curr):
            curr = os.path.expanduser("~")

        parent = os.path.dirname(curr) if curr != "/" else None

        # 시스템 및 캐시 디렉토리 필터링 (경량화 & 보안)
        excluded_names = {
            ".git", ".venv", "venv", "node_modules", ".idea", ".vscode",
            ".gradle", "build", "target", "__pycache__", ".DS_Store", "Library"
        }

        directories = []
        try:
            with os.scandir(curr) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False) and entry.name not in excluded_names and not entry.name.startswith("."):
                            branch = self.get_git_branch(entry.path)
                            directories.append({
                                "name": entry.name,
                                "path": entry.path,
                                "is_git": branch is not None,
                                "git_branch": branch
                            })
                    except (PermissionError, OSError):
                        continue
        except (PermissionError, OSError):
            pass

        # Git 저장소 우선, 그 후 알파벳 순 정렬
        directories.sort(key=lambda x: (not x["is_git"], x["name"].lower()))

        curr_branch = self.get_git_branch(curr)
        return {
            "current_path": curr,
            "parent_path": parent,
            "is_git_repo": curr_branch is not None,
            "git_branch": curr_branch,
            "directories": directories,
            "recent_repositories": self.recent_repositories,
            "active_repo": self.active_repo
        }
