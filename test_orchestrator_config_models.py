# test_orchestrator_config_models.py
import unittest
import os
from harnex.orchestrator.config import OrchestratorConfig, load_orchestrator_config
from harnex.orchestrator.models import TaskDAG, SubTask, TaskState, SignalMessage, SignalType, validate_dag


class TestOrchestratorConfigAndModels(unittest.TestCase):
    def test_default_config_loading_no_hardcoding(self):
        config = load_orchestrator_config()
        self.assertEqual(config.max_subtasks, 20)
        self.assertEqual(config.max_dag_depth, 5)
        self.assertEqual(config.task_timeout_seconds, 600)
        self.assertEqual(config.worktree_root, "~/.harnex/worktrees")

    def test_env_var_override(self):
        os.environ["HARNEX_ORCH_MAX_SUBTASKS"] = "15"
        os.environ["HARNEX_ORCH_TASK_TIMEOUT_SECONDS"] = "300"
        try:
            config = load_orchestrator_config()
            self.assertEqual(config.max_subtasks, 15)
            self.assertEqual(config.task_timeout_seconds, 300)
        finally:
            del os.environ["HARNEX_ORCH_MAX_SUBTASKS"]
            del os.environ["HARNEX_ORCH_TASK_TIMEOUT_SECONDS"]

    def test_valid_dag_validation(self):
        config = OrchestratorConfig()
        dag = TaskDAG(
            dag_id="dag_test_1",
            title="Test Multi-Agent DAG",
            subtasks={
                "sub1": SubTask(subtask_id="sub1", parent_task_id="dag_test_1", title="Task 1", instruction="Write model definition"),
                "sub2": SubTask(subtask_id="sub2", parent_task_id="dag_test_1", title="Task 2", instruction="Write API controller", dependencies=["sub1"]),
                "sub3": SubTask(subtask_id="sub3", parent_task_id="dag_test_1", title="Task 3", instruction="Write unit tests", dependencies=["sub1", "sub2"])
            }
        )
        # Should pass without error
        validate_dag(dag, config)

    def test_circular_dependency_detection(self):
        config = OrchestratorConfig()
        dag = TaskDAG(
            dag_id="dag_cycle",
            title="Cyclic DAG",
            subtasks={
                "subA": SubTask(subtask_id="subA", parent_task_id="dag_cycle", title="A", instruction="Task A instruction", dependencies=["subB"]),
                "subB": SubTask(subtask_id="subB", parent_task_id="dag_cycle", title="B", instruction="Task B instruction", dependencies=["subA"])
            }
        )
        with self.assertRaises(ValueError) as ctx:
            validate_dag(dag, config)
        self.assertIn("Circular dependency", str(ctx.exception))

    def test_dangling_dependency_detection(self):
        config = OrchestratorConfig()
        dag = TaskDAG(
            dag_id="dag_dangling",
            title="Dangling DAG",
            subtasks={
                "sub1": SubTask(subtask_id="sub1", parent_task_id="dag_dangling", title="1", instruction="Valid instruction", dependencies=["ghost_task"])
            }
        )
        with self.assertRaises(ValueError) as ctx:
            validate_dag(dag, config)
        self.assertIn("dangling dependency", str(ctx.exception))

    def test_instruction_too_short_detection(self):
        config = OrchestratorConfig(min_instruction_length=10)
        dag = TaskDAG(
            dag_id="dag_short",
            title="Short DAG",
            subtasks={
                "sub1": SubTask(subtask_id="sub1", parent_task_id="dag_short", title="1", instruction="abc")
            }
        )
        with self.assertRaises(ValueError) as ctx:
            validate_dag(dag, config)
        self.assertIn("too short", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
