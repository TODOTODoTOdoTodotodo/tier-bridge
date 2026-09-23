import unittest
import os
import re
import subprocess
import json

class TestSessionAggregationAndDashboard(unittest.TestCase):
    def test_live_log_waterfall_in_parse_args(self):
        """ parse_args should prioritize live harness.log over dev harness.log """
        import analyze_usage
        live_log = os.path.expanduser("~/.tierbridge/live/harness.log")
        if os.path.exists(live_log):
            parser_args = analyze_usage.parse_args.__code__.co_consts
            # Verify the default log logic prioritizes live_log
            args = analyze_usage.parse_args([])
            self.assertEqual(args.log_file, live_log)

    def test_session_aggregation_01a0cbe5(self):
        """ Session 01a0cbe5 must be aggregated correctly with 10 turns and ~6.16 credits """
        live_log = os.path.expanduser("~/.tierbridge/live/harness.log")
        if not os.path.exists(live_log):
            self.skipTest("Live harness.log not found")

        cmd = [
            os.path.expanduser("~/.tierbridge/live/.venv/bin/python"),
            "analyze_usage.py",
            "-s", "01a0cbe5"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("총 성공 요청 수 (Requests) : 10 회", result.stdout)
        self.assertIn("01a0cbe5-af35-7472-b81f-bf3b3d192dbc", result.stdout)
        self.assertIn("6.16 Credits", result.stdout)

    def test_dashboard_html_contains_session_and_safe_filtering(self):
        """ usage_dashboard.html must contain 01a0cbe5 and session-first filter logic """
        html_path = "usage_dashboard.html"
        self.assertTrue(os.path.exists(html_path), "usage_dashboard.html should exist")
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("01a0cbe5-af35-7472-b81f-bf3b3d192dbc", content)
        self.assertIn("2026-09", content)
        # Ensure session-first filter logic is present to prevent month filter conflict
        self.assertIn("allRecords.filter(r => r.session_id === sessionToFilter", content)
        self.assertIn("mSelect.value = 'ALL'", content)

if __name__ == "__main__":
    unittest.main()
