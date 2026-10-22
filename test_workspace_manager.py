# test_workspace_manager.py
import unittest
import tempfile
import os
import shutil
from fastapi.testclient import TestClient

from harness import app
from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.workspace_manager import WorkspaceManager


class TestWorkspaceManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = OrchestratorConfig()
        self.wm = WorkspaceManager(self.config, base_dir=self.test_dir)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_git_branch_detection(self):
        # 1. Non-git directory
        branch = WorkspaceManager.get_git_branch(self.test_dir)
        self.assertIsNone(branch)

        # 2. Git directory with HEAD
        git_dir = os.path.join(self.test_dir, ".git")
        os.makedirs(git_dir, exist_ok=True)
        with open(os.path.join(git_dir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/feature/test-branch\n")

        branch = WorkspaceManager.get_git_branch(self.test_dir)
        self.assertEqual(branch, "feature/test-branch")

    def test_browse_directory(self):
        # Create subdirectories
        sub1 = os.path.join(self.test_dir, "repo-a")
        sub2 = os.path.join(self.test_dir, "plain-dir")
        os.makedirs(os.path.join(sub1, ".git"), exist_ok=True)
        os.makedirs(sub2, exist_ok=True)

        res = self.wm.browse_directory(self.test_dir)
        self.assertEqual(res["current_path"], os.path.abspath(self.test_dir))
        dir_names = [d["name"] for d in res["directories"]]
        self.assertIn("repo-a", dir_names)
        self.assertIn("plain-dir", dir_names)

        # Check is_git flag
        repo_a_entry = next(d for d in res["directories"] if d["name"] == "repo-a")
        self.assertTrue(repo_a_entry["is_git"])

    def test_select_workspace(self):
        new_repo = os.path.join(self.test_dir, "my-repo")
        os.makedirs(new_repo, exist_ok=True)

        res = self.wm.select_workspace(new_repo)
        self.assertEqual(res["status"], "SELECTED")
        self.assertEqual(res["active_repo"], os.path.abspath(new_repo))
        self.assertEqual(self.wm.active_repo, os.path.abspath(new_repo))
        self.assertIn(os.path.abspath(new_repo), self.wm.recent_repositories)

    def test_api_browse_and_select(self):
        # 1. GET /v1/orchestrator/fs/browse
        resp = self.client.get("/v1/orchestrator/fs/browse")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("current_path", data)
        self.assertIn("directories", data)

        # 2. POST /v1/orchestrator/workspace/select
        sel_resp = self.client.post("/v1/orchestrator/workspace/select", json={"repo_path": self.test_dir})
        self.assertEqual(sel_resp.status_code, 200)
        sel_data = sel_resp.json()
        self.assertEqual(sel_data["status"], "SELECTED")

        # 3. GET /v1/orchestrator/tasks contains active_workspace
        tasks_resp = self.client.get("/v1/orchestrator/tasks")
        self.assertEqual(tasks_resp.status_code, 200)
        tasks_data = tasks_resp.json()
        self.assertIn("active_workspace", tasks_data)
        self.assertEqual(tasks_data["active_workspace"]["path"], os.path.abspath(self.test_dir))


if __name__ == "__main__":
    unittest.main()
