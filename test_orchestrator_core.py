# test_orchestrator_core.py
import asyncio
import unittest
from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import TaskDAG, SubTask, TaskState, SignalMessage, SignalType
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.sandbox import WorktreeSandboxManager


class TestOrchestratorCore(unittest.IsolatedAsyncioTestCase):
    async def test_signal_bus_state_transitions(self):
        config = OrchestratorConfig()
        bus = SignalBus(config)

        task = SubTask(
            subtask_id="sub_test_1",
            parent_task_id="dag_1",
            title="Entity implementation",
            instruction="Create Entity class"
        )
        bus.register_subtask(task)
        self.assertEqual(task.state, TaskState.PENDING)

        # 1. Emit STARTED
        res = await bus.emit_signal(SignalMessage(task_id="sub_test_1", signal_type=SignalType.STARTED, worker_pid=12345))
        self.assertTrue(res)
        self.assertEqual(task.state, TaskState.RUNNING)
        self.assertEqual(task.worker_pid, 12345)

        # 2. Emit PROGRESS
        res = await bus.emit_signal(SignalMessage(task_id="sub_test_1", signal_type=SignalType.PROGRESS, progress_percent=50.0, loc_modified=30))
        self.assertTrue(res)
        self.assertEqual(task.loc_modified, 30)

        # 3. Emit COMPLETED
        res = await bus.emit_signal(SignalMessage(task_id="sub_test_1", signal_type=SignalType.COMPLETED, loc_modified=50, tokens_used=1000, credits_used=0.25))
        self.assertTrue(res)
        self.assertEqual(task.state, TaskState.COMPLETED)
        self.assertEqual(task.loc_modified, 50)
        self.assertEqual(task.tokens_used, 1000)

        # 4. Out-of-order signal on COMPLETED task must be rejected (Idempotency)
        res_late = await bus.emit_signal(SignalMessage(task_id="sub_test_1", signal_type=SignalType.PROGRESS, progress_percent=60.0))
        self.assertFalse(res_late)
        self.assertEqual(task.state, TaskState.COMPLETED)

    async def test_diff_patch_payload_bomb_guard(self):
        config = OrchestratorConfig(max_patch_size_bytes=100)  # Very small threshold for testing
        bus = SignalBus(config)

        task = SubTask(
            subtask_id="sub_bomb",
            parent_task_id="dag_1",
            title="Big diff",
            instruction="Huge change"
        )
        bus.register_subtask(task)
        await bus.emit_signal(SignalMessage(task_id="sub_bomb", signal_type=SignalType.STARTED))

        # Emit patch larger than 100 bytes
        huge_patch = "A" * 200
        res = await bus.emit_signal(SignalMessage(task_id="sub_bomb", signal_type=SignalType.COMPLETED, diff_patch=huge_patch))
        self.assertTrue(res)
        # Task should be transitioned to FAILED due to payload limit
        self.assertEqual(task.state, TaskState.FAILED)
        self.assertIn("exceeded max_patch_size_bytes", task.error_message)

    async def test_path_traversal_defense(self):
        config = OrchestratorConfig()
        mgr = WorktreeSandboxManager(base_repo_dir=".", config=config)

        # Path traversal with ../ must be rejected immediately
        with self.assertRaises(ValueError):
            mgr.get_worktree_path("../../etc/passwd")

        # Invalid characters must be rejected
        with self.assertRaises(ValueError):
            mgr.get_worktree_path("subtask;rm -rf /")

        # Valid subtask ID must pass
        valid_path = mgr.get_worktree_path("subtask-valid_123")
        self.assertTrue(valid_path.endswith("subtask-valid_123"))


if __name__ == "__main__":
    unittest.main()
