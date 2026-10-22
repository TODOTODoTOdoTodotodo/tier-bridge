# test_orchestrator_chat_and_presence.py
import unittest
import asyncio
from fastapi.testclient import TestClient

from harness import app
from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import TaskDAG, SubTask, TaskState, SignalMessage, SignalType, ActivityType
from harnex.orchestrator.memory_bridge import TaskMemoryBridge
from harnex.orchestrator.activity_tracker import ActivityTracker
from harnex.orchestrator.chat_manager import ChatManager
from harnex.orchestrator.signal_bus import SignalBus


class TestOrchestratorChatAndPresence(unittest.TestCase):
    def setUp(self):
        self.config = OrchestratorConfig(
            event_history_limit=5,
            memory_injection_enabled=True,
            memory_injection_top_k=2
        )
        self.tracker = ActivityTracker(self.config)
        self.signal_bus = SignalBus(self.config, activity_tracker=self.tracker)
        self.chat_mgr = ChatManager(self.tracker, self.signal_bus)
        self.client = TestClient(app)

    def test_task_memory_bridge_srp(self):
        """ TaskMemoryBridge should search without error and format prompt """
        bridge = TaskMemoryBridge(self.config)
        sub = SubTask(
            subtask_id="sub_test_01",
            parent_task_id="dag_01",
            title="Lombok 어노테이션 리팩토링",
            instruction="UserEntity에 @RequiredArgsConstructor 적용"
        )
        mems = bridge.prefetch_memories_for_subtask(sub)
        self.assertIsInstance(mems, list)
        formatted = bridge.format_memory_injection_prompt(mems)
        self.assertIsInstance(formatted, str)

    def test_activity_tracker_ring_buffer(self):
        """ ActivityTracker should enforce FIFO ring buffer capacity """
        dag_id = "dag_fifo_test"
        sub = SubTask(
            subtask_id="sub_1",
            parent_task_id=dag_id,
            title="Sub 1",
            instruction="Do something"
        )
        # Record 8 items in a buffer of limit 5
        for i in range(8):
            sig = SignalMessage(
                task_id="sub_1",
                signal_type=SignalType.PROGRESS,
                message=f"Step {i}"
            )
            self.tracker.record_signal_activity(dag_id, sub, sig)

        activities = self.tracker.get_dag_activities(dag_id)
        self.assertEqual(len(activities), 5)
        # Oldest should be Step 3, newest should be Step 7
        self.assertIn("Step 7", activities[-1]["message"])
        self.assertIn("Step 3", activities[0]["message"])

    def test_chat_manager_parsing_and_injection(self):
        """ ChatManager should correctly parse mentions and record user intervention """
        # Mention parsing
        target, clean_msg = self.chat_mgr.parse_target_subtask("@sub_auth_01 트랜잭션 롤백 테스트 작성")
        self.assertEqual(target, "sub_auth_01")
        self.assertEqual(clean_msg, "트랜잭션 롤백 테스트 작성")

        # No mention
        target_none, clean_msg2 = self.chat_mgr.parse_target_subtask("전체 워커 진행 보고 요망")
        self.assertIsNone(target_none)
        self.assertEqual(clean_msg2, "전체 워커 진행 보고 요망")

        # Handle user message
        result = asyncio.run(self.chat_mgr.handle_user_message("dag_chat_test", "@sub_auth_01 트랜잭션 롤백 테스트 작성"))
        self.assertEqual(result["status"], "SENT")
        self.assertEqual(result["target_subtask_id"], "sub_auth_01")
        self.assertEqual(result["activity"]["tier"], "OPERATOR ➔ sub_auth_01")

        # Check pending hints
        hints = self.chat_mgr.get_and_clear_hints_for_subtask("sub_auth_01")
        self.assertEqual(hints, ["트랜잭션 롤백 테스트 작성"])
        self.assertEqual(self.chat_mgr.get_and_clear_hints_for_subtask("sub_auth_01"), [])

        # Verify no duplicate activity in ActivityTracker
        feed = self.tracker.get_dag_activities("dag_chat_test")
        user_chat_items = [item for item in feed if item["activity_type"] == "USER_CHAT"]
        self.assertEqual(len(user_chat_items), 1)
        self.assertEqual(user_chat_items[0]["tier"], "OPERATOR ➔ sub_auth_01")

    def test_api_chat_and_events_endpoints(self):
        """ Test /v1/orchestrator/tasks/{dag_id}/chat and /v1/orchestrator/tasks/{dag_id}/events """
        dag_id = "dag_api_test"
        # 1. Dispatch a test DAG
        payload = {
            "dag_id": dag_id,
            "title": "API 테스트 DAG",
            "subtasks": {
                "sub_1": {
                    "subtask_id": "sub_1",
                    "parent_task_id": dag_id,
                    "title": "Sub 1 Test",
                    "instruction": "Test instruction",
                    "assigned_tier": "SILVER"
                }
            }
        }
        resp = self.client.post("/v1/orchestrator/dispatch", json=payload)
        self.assertEqual(resp.status_code, 200)

        # 2. Post user chat to DAG
        chat_resp = self.client.post(f"/v1/orchestrator/tasks/{dag_id}/chat", json={"message": "@sub_1 테스트 힌트 전달"})
        self.assertEqual(chat_resp.status_code, 200)
        chat_data = chat_resp.json()
        self.assertEqual(chat_data["target_subtask_id"], "sub_1")

        # 3. Get events history for DAG
        events_resp = self.client.get(f"/v1/orchestrator/tasks/{dag_id}/events")
        self.assertEqual(events_resp.status_code, 200)
        events_data = events_resp.json()
        self.assertEqual(events_data["dag_id"], dag_id)
        self.assertTrue(len(events_data["activities"]) >= 1)
        # Ensure USER_CHAT is not duplicated
        chat_acts = [a for a in events_data["activities"] if a["activity_type"] == "USER_CHAT"]
        self.assertEqual(len(chat_acts), 1)
        self.assertEqual(chat_acts[0]["tier"], "OPERATOR ➔ sub_1")

        # 4. Cancel DAG task
        cancel_resp = self.client.post(f"/v1/orchestrator/tasks/{dag_id}/cancel")
        self.assertEqual(cancel_resp.status_code, 200)
        cancel_data = cancel_resp.json()
        self.assertEqual(cancel_data["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
