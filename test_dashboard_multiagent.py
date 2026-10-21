# test_dashboard_multiagent.py
import os
import re
import sys
import unittest
from fastapi.testclient import TestClient

import analyze_usage
import harness


class TestDashboardMultiAgent(unittest.TestCase):
    """
    Test suite for Track B: Dashboard UI & Multi-Agent Visualization.
    Validates API stats generation, schema backward-compatibility,
    and HTML DOM structure for the multiagent tasks tab.
    """

    def test_stats_contains_orchestrator_section(self):
        """
        Verify that generate_stats_json in analyze_usage.py returns
        the expected orchestrator schema without breaking existing fields.
        """
        stats = analyze_usage.generate_stats_json()
        self.assertIsInstance(stats, dict)

        # Existing field invariants preservation
        for field in ("total_records", "real_credits", "total_credits", "records", "balance"):
            self.assertIn(field, stats, f"Existing field '{field}' must be preserved")

        # Orchestrator section verification
        self.assertIn("orchestrator", stats, "'orchestrator' section must be present")
        orch = stats["orchestrator"]
        self.assertIsInstance(orch, dict)
        self.assertIn("enabled", orch)
        self.assertTrue(orch["enabled"])
        self.assertIn("active_tasks_count", orch)
        self.assertIn("completed_tasks_count", orch)
        self.assertIn("failed_tasks_count", orch)
        self.assertIn("tasks", orch)
        self.assertIsInstance(orch["tasks"], list)

    def test_harness_dashboard_stats_api_endpoint(self):
        """
        Verify that HTTP GET /v1/dashboard/stats returns orchestrator telemetry.
        """
        client = TestClient(harness.app)
        resp = client.get("/v1/dashboard/stats")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertIn("orchestrator", data)
        orch = data["orchestrator"]
        self.assertIn("enabled", orch)
        self.assertIn("active_tasks_count", orch)
        self.assertIn("completed_tasks_count", orch)
        self.assertIn("failed_tasks_count", orch)
        self.assertIn("tasks", orch)
        self.assertIsInstance(orch["tasks"], list)

        # Confirm non-destruction of existing records & balances
        self.assertIn("records", data)
        self.assertIn("total_records", data)
        self.assertIn("total_credits", data)
        self.assertIn("real_credits", data)
        self.assertIn("balance", data)

    def test_usage_dashboard_html_tab_navigation(self):
        """
        Verify usage_dashboard.html contains the 5th tab button in #tabNavigation
        with the exact requested attributes and badge.
        """
        html_path = "usage_dashboard.html"
        self.assertTrue(os.path.exists(html_path), "usage_dashboard.html must exist")

        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # #tabNavigation container
        self.assertIn('id="tabNavigation"', content)

        # Tab button with data-tab="tasks"
        self.assertIn('data-tab="tasks"', content)
        self.assertIn("멀티에이전트 (Tasks)", content)
        self.assertIn("fa-diagram-project", content)

        # #activeTasksBadge
        self.assertIn('id="activeTasksBadge"', content)

    def test_usage_dashboard_html_content_and_cards(self):
        """
        Verify usage_dashboard.html contains #tabContent-tasks with:
        - 4-Card header summary: 총 태스크, 실행 중 워커 (Active), 누적 생성 LOC, 절감 크레딧
        - Task DAG / subtasks list container
        - Elegant empty-state card with exact instruction text
        """
        html_path = "usage_dashboard.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Main section #tabContent-tasks
        self.assertIn('id="tabContent-tasks"', content)

        # 4-Card Header Summary
        self.assertIn("총 태스크", content)
        self.assertIn("실행 중 워커 (Active)", content)
        self.assertIn("누적 생성 LOC", content)
        self.assertIn("절감 크레딧", content)

        # Metric element IDs
        self.assertIn('id="kpiTasksTotal"', content)
        self.assertIn('id="kpiTasksActiveWorkers"', content)
        self.assertIn('id="kpiTasksLoc"', content)
        self.assertIn('id="kpiTasksSavedCredits"', content)

        # Empty state card with exact text
        self.assertIn('id="tasksEmptyState"', content)
        self.assertIn("현재 실행 중인 비동기 오케스트레이터 태스크가 없습니다.", content)
        self.assertIn("harnex-task dispatch", content)

        # Subtasks container
        self.assertIn('id="tasksContainer"', content)

        # Subtask card attributes rendered in renderTasksView JS
        self.assertIn("PID:", content)
        self.assertIn("renderTasksView", content)
        self.assertIn("switchTab", content)
        self.assertIn("switchDashboardTab", content)

    def test_tab_switching_logic_javascript(self):
        """
        Ensure switchTab('tasks') and switchDashboardTab('tasks') are implemented smoothly.
        """
        html_path = "usage_dashboard.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("function switchDashboardTab(tab)", content)
        self.assertIn("function switchTab(tabName)", content)
        self.assertIn("tab === 'tasks'", content)
        self.assertIn("renderTasksView(orchestratorData)", content)

    def test_live_sync_updates_active_tasks_badge(self):
        """
        Verify fetchLiveDashboardStats updates activeTasksBadge and tasks view without full-page reload.
        """
        html_path = "usage_dashboard.html"
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("activeBadge.innerText = `${activeCount} RUNNING`", content)
        self.assertIn("if (currentDashboardTab === 'tasks')", content)


if __name__ == "__main__":
    unittest.main()
