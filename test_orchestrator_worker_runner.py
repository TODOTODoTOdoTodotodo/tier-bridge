# test_orchestrator_worker_runner.py
import os
import shutil
import tempfile
import unittest

from harnex.orchestrator.worker_runner import (
    tool_glob_files,
    tool_read_file,
    tool_write_file,
    parse_action,
    execute_tool,
)


class TestWorkerRunnerToolsAndParser(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="harnex_worker_test_")
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_glob_and_read_write_file(self):
        # 1. Write file
        res = tool_write_file("docs/sample.md", "# Sample Document\nHello world")
        self.assertIn("Successfully wrote", res)
        self.assertTrue(os.path.exists("docs/sample.md"))

        # 2. Glob files
        glob_res = tool_glob_files("*.md")
        self.assertIn("docs/sample.md", glob_res)

        # 3. Read file
        content = tool_read_file("docs/sample.md")
        self.assertIn("# Sample Document", content)
        self.assertIn("Hello world", content)

    def test_path_traversal_prevention(self):
        # Attempt traversal outside worktree
        res = tool_read_file("../../outside.txt")
        self.assertIn("Error: Path traversal", res)

        res_write = tool_write_file("../outside.txt", "evil")
        self.assertIn("Error: Path traversal", res_write)

    def test_parse_action_variations(self):
        # 1. Standard regex
        text1 = 'THOUGHT: Let me check markdown files\nACTION: glob_files(pattern="**/*.md")'
        thought, act, args = parse_action(text1)
        self.assertEqual(act, "glob_files")
        self.assertEqual(args.get("pattern"), "**/*.md")
        self.assertIn("check markdown files", thought)

        # 2. Write file with multiline content
        text2 = 'THOUGHT: Writing report\nACTION: write_file(path="report.md")\n```markdown\n# Final Report\n- Point 1\n```'
        thought, act, args = parse_action(text2)
        self.assertEqual(act, "write_file")
        self.assertEqual(args.get("path"), "report.md")
        self.assertIn("# Final Report", args.get("content", ""))

        # 3. Final answer
        text3 = 'THOUGHT: Done with analysis\nFINAL_ANSWER: Analysis complete. Found 3 files.'
        thought, act, args = parse_action(text3)
        self.assertEqual(act, "FINAL_ANSWER")
        self.assertIn("Analysis complete", args.get("message", ""))

    def test_execute_tool(self):
        tool_write_file("test.txt", "12345")
        res = execute_tool("read_file", {"path": "test.txt"})
        self.assertIn("12345", res)

        unknown = execute_tool("non_existent_tool", {})
        self.assertIn("Error: Unknown tool", unknown)


if __name__ == "__main__":
    unittest.main()
