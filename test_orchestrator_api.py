# test_orchestrator_api.py
import unittest
from fastapi.testclient import TestClient

from harness import app
from harnex.orchestrator.models import TaskDAG, SubTask, SignalMessage, SignalType


class TestOrchestratorAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_config_no_hardcoding(self):
        resp = self.client.get("/v1/orchestrator/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("max_subtasks", data)
        self.assertIn("task_timeout_seconds", data)
        self.assertIn("worktree_root", data)

    def test_list_tasks_empty_state(self):
        resp = self.client.get("/v1/orchestrator/tasks")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("enabled"))
        self.assertIsInstance(data.get("tasks"), list)

    def test_dispatch_and_signal_webhook(self):
        dag_payload = {
            "dag_id": "dag_api_test_1",
            "title": "API Test Pipeline",
            "subtasks": {
                "sub_api_1": {
                    "subtask_id": "sub_api_1",
                    "parent_task_id": "dag_api_test_1",
                    "title": "Subtask 1",
                    "instruction": "Instruction 1",
                    "assigned_tier": "BRONZE"
                }
            }
        }
        resp = self.client.post("/v1/orchestrator/dispatch", json=dag_payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "DISPATCHED")

        # Test worker webhook signal
        signal_payload = {
            "task_id": "sub_api_1",
            "signal_type": "STARTED",
            "worker_pid": 99999
        }
        sig_resp = self.client.post("/v1/orchestrator/tasks/sub_api_1/signal", json=signal_payload)
        self.assertEqual(sig_resp.status_code, 200)
        self.assertEqual(sig_resp.json()["task_id"], "sub_api_1")

    def test_subtask_credit_synchronization(self):
        from harnex.credit_interceptor import interceptor
        interceptor.session_usage["task_sub_credit_test"] = {
            "session_id": "task_sub_credit_test",
            "turns": 5,
            "input_tokens": 15000,
            "output_tokens": 3000,
            "total_tokens": 18000,
            "real_credits": 1.4520,
            "loc": 120
        }

        dag_payload = {
            "dag_id": "dag_credit_sync",
            "title": "Credit Sync Pipeline",
            "subtasks": {
                "sub_credit_test": {
                    "subtask_id": "sub_credit_test",
                    "parent_task_id": "dag_credit_sync",
                    "title": "Credit Subtask",
                    "instruction": "Test credits",
                    "assigned_tier": "SILVER"
                }
            }
        }
        self.client.post("/v1/orchestrator/dispatch", json=dag_payload)

        # Worker sends signal with default 0 credits
        sig_payload = {
            "task_id": "sub_credit_test",
            "signal_type": "COMPLETED",
            "worker_pid": 88888,
            "loc_modified": 120,
            "tokens_used": 0,
            "credits_used": 0.0
        }
        sig_resp = self.client.post("/v1/orchestrator/tasks/sub_credit_test/signal", json=sig_payload)
        self.assertEqual(sig_resp.status_code, 200)

        # Verify task detail returns synchronized ground truth real credits
        detail_resp = self.client.get("/v1/orchestrator/tasks/dag_credit_sync")
        self.assertEqual(detail_resp.status_code, 200)
        sub = detail_resp.json()["subtasks"]["sub_credit_test"]
        self.assertAlmostEqual(sub["credits_used"], 1.4520, places=4)
        self.assertEqual(sub["tokens_used"], 18000)
        self.assertEqual(sub["turns_completed"], 5)

    def test_dispatch_circular_dependency_returns_400(self):
        cyclic_payload = {
            "dag_id": "dag_cyclic_api",
            "title": "Cyclic API Pipeline",
            "subtasks": {
                "subA": {
                    "subtask_id": "subA",
                    "parent_task_id": "dag_cyclic_api",
                    "title": "A",
                    "instruction": "Instruction A",
                    "dependencies": ["subB"]
                },
                "subB": {
                    "subtask_id": "subB",
                    "parent_task_id": "dag_cyclic_api",
                    "title": "B",
                    "instruction": "Instruction B",
                    "dependencies": ["subA"]
                }
            }
        }
        resp = self.client.post("/v1/orchestrator/dispatch", json=cyclic_payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Circular dependency", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
