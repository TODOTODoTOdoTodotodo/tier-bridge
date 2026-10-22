# test_orchestrator_scheduler.py
import asyncio
import unittest
from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import TaskDAG, SubTask, TaskState, SignalMessage, SignalType
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.scheduler import DAGScheduler


class MockSandboxManager:
    def __init__(self):
        self.created = []

    async def create_sandbox(self, subtask_id: str, base_commit: str = "HEAD", *args, **kwargs) -> str:
        self.created.append(subtask_id)
        return f"/tmp/mock_worktrees/{subtask_id}"

    async def cleanup_sandbox(self, subtask_id: str, *args, **kwargs) -> None:
        pass


class MockWorkerPool:
    def __init__(self, signal_bus: SignalBus):
        self.signal_bus = signal_bus
        self.spawned = []

    async def spawn_worker(self, subtask: SubTask, worktree_path: str, cmd=None, signal_bus=None):
        self.spawned.append(subtask.subtask_id)
        # Simulate worker async execution: emit STARTED then COMPLETED after short sleep
        asyncio.create_task(self._simulate_worker(subtask.subtask_id))

    async def _simulate_worker(self, subtask_id: str):
        await self.signal_bus.emit_signal(SignalMessage(task_id=subtask_id, signal_type=SignalType.STARTED))
        await asyncio.sleep(0.01)
        await self.signal_bus.emit_signal(SignalMessage(task_id=subtask_id, signal_type=SignalType.COMPLETED, loc_modified=25, tokens_used=500, credits_used=0.05))

    async def terminate_worker(self, subtask_id: str):
        pass


class TestOrchestratorScheduler(unittest.IsolatedAsyncioTestCase):
    async def test_dag_sequential_and_parallel_dispatch(self):
        config = OrchestratorConfig()
        bus = SignalBus(config)
        sandbox = MockSandboxManager()
        pool = MockWorkerPool(bus)

        # sub1 and sub2 run in parallel; sub3 depends on both
        dag = TaskDAG(
            dag_id="dag_e2e_1",
            title="E2E Pipeline Test",
            subtasks={
                "sub1": SubTask(subtask_id="sub1", parent_task_id="dag_e2e_1", title="Task 1", instruction="Do work 1"),
                "sub2": SubTask(subtask_id="sub2", parent_task_id="dag_e2e_1", title="Task 2", instruction="Do work 2"),
                "sub3": SubTask(subtask_id="sub3", parent_task_id="dag_e2e_1", title="Task 3", instruction="Do work 3", dependencies=["sub1", "sub2"]),
            }
        )

        scheduler = DAGScheduler(dag, bus, sandbox, pool, config)
        final_state = await scheduler.run()

        self.assertEqual(final_state, TaskState.COMPLETED)
        self.assertEqual(dag.state, TaskState.COMPLETED)
        self.assertEqual(dag.subtasks["sub1"].state, TaskState.COMPLETED)
        self.assertEqual(dag.subtasks["sub2"].state, TaskState.COMPLETED)
        self.assertEqual(dag.subtasks["sub3"].state, TaskState.COMPLETED)
        self.assertEqual(len(pool.spawned), 3)


if __name__ == "__main__":
    unittest.main()
