import os
import sys
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from src.tierbridge.credit_interceptor import CreditInterceptor
import analyze_usage

class TestCreditInterceptor(unittest.TestCase):
    def setUp(self):
        self.interceptor = CreditInterceptor()
        self.interceptor.last_known_used = None
        self.interceptor.last_known_remaining = None

    def test_interceptor_delta_calculation(self):
        async def run_test():
            # Turn 1: Initialization
            with patch.object(self.interceptor, "fetch_enterprise_usage", new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = {
                    "limit": 1500.0,
                    "used": 119.85,
                    "remaining": 1380.15,
                    "used_percent": 8,
                    "remaining_percent": 92,
                    "reset_at": 1788220800
                }
                await self.interceptor.track_turn_delta(
                    session_id="sess_test1",
                    decision="GOLD",
                    model="gpt-5.6-terra",
                    in_tok=2500,
                    out_tok=450,
                    loc=35,
                    est_cost=0.03048,
                    now_str="2026-08-18 16:45:00"
                )
                self.assertEqual(self.interceptor.last_known_used, 119.85)

                # Turn 2: Subsequent Turn with 0.15 Delta
                mock_fetch.return_value = {
                    "limit": 1500.0,
                    "used": 120.00,
                    "remaining": 1380.00,
                    "used_percent": 8,
                    "remaining_percent": 92,
                    "reset_at": 1788220800
                }
                await self.interceptor.track_turn_delta(
                    session_id="sess_test1",
                    decision="PLATINUM",
                    model="gpt-5.6-terra",
                    in_tok=3000,
                    out_tok=600,
                    loc=50,
                    est_cost=0.04000,
                    now_str="2026-08-18 16:46:00"
                )
                self.assertEqual(self.interceptor.last_known_used, 120.00)
                self.assertEqual(self.interceptor.last_known_remaining, 1380.00)

        asyncio.run(run_test())

    def test_log_regex_parsing(self):
        # 1. Legacy format with cost=$... USD
        legacy_log_line = "[2026-08-18 16:45:00] [sid: sess_test1] ➔ [USAGE: GOLD] (gpt-5.6-terra) | input=2500 output=450 tokens | real_credit=0.1524 | balance=1380.15 | loc=35 lines | cost=$0.030480 USD"
        
        usage_pattern = analyze_usage.re.compile(
            r"^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[USAGE(?::\s*(?P<decision_opt>[^\]]+))?\](?:\s+(?P<decision_legacy>[^\s(]+))?\s+\((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| real_credit=(?P<real_credit>[\d\.]+))?(?: \| balance=(?P<balance>[\d\.]+))?(?: \| loc=(?P<loc>\d+) lines)?(?:\s*\|\s*cost=\$(?P<cost>[\d\.]+) USD)?"
        )
        
        m_leg = usage_pattern.search(legacy_log_line)
        self.assertIsNotNone(m_leg)
        self.assertEqual(m_leg.group("sid"), "sess_test1")
        self.assertEqual(m_leg.group("decision_opt"), "GOLD")
        self.assertEqual(m_leg.group("cost"), "0.030480")

        # 2. Modern credit-first format without cost=$... USD
        modern_log_line = "[2026-08-18 16:45:00] [sid: sess_test1] ➔ [USAGE: GOLD] (gpt-5.6-terra) | input=2500 output=450 tokens | real_credit=0.1524 | balance=1380.15 | loc=35 lines"
        m_mod = usage_pattern.search(modern_log_line)
        self.assertIsNotNone(m_mod)
        self.assertEqual(m_mod.group("sid"), "sess_test1")
        self.assertEqual(m_mod.group("decision_opt"), "GOLD")
        self.assertEqual(m_mod.group("real_credit"), "0.1524")
        self.assertEqual(m_mod.group("balance"), "1380.15")
        self.assertIsNone(m_mod.group("cost"))

    def test_workspace_pool_parsing(self):
        async def run_test():
            mock_client = AsyncMock()
            mock_res = MagicMock()
            mock_res.status_code = 200
            mock_res.json.return_value = {
                "credits": {
                    "has_credits": False,
                    "balance": "0",
                    "overage_limit_reached": True
                },
                "rate_limit_reached_type": {
                    "type": "workspace_member_credits_depleted"
                },
                "rate_limit_upsell": {
                    "title": "You've reached your workspace credit limit",
                    "description": "Your workspace is out of credits. Ask your workspace owner to add more."
                },
                "spend_control": {
                    "individual_limit": {
                        "limit": "3000",
                        "used": "462.04",
                        "remaining": "2537.96",
                        "reset_at": 1790812800
                    }
                }
            }
            mock_client.get.return_value = mock_res
            
            with patch.object(self.interceptor, "get_client", return_value=mock_client):
                res = await self.interceptor.fetch_enterprise_usage("mock_token", "mock_acc")
                self.assertIsNotNone(res)
                self.assertEqual(res["limit"], 3000.0)
                self.assertEqual(res["used"], 462.04)
                self.assertIn("workspace_pool", res)
                wp = res["workspace_pool"]
                self.assertTrue(wp["is_depleted"])
                self.assertEqual(wp["status"], "DEPLETED")
                self.assertEqual(wp["balance"], 0.0)
                self.assertEqual(wp["rate_limit_type"], "workspace_member_credits_depleted")

        asyncio.run(run_test())

    def test_harness_dashboard_stats_modern_log(self):
        import tempfile
        from fastapi.testclient import TestClient
        import harness

        client = TestClient(harness.app)
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            temp_path = f.name
            f.write(
                "[2026-10-01 11:46:20] [sid: 01a0f4da-0ea0-7691-a1cb-fac895418797] ➔ [DECISION: STANDARD 3-TIER ROUTER] PLATINUM (gpt-6-sol:medium) [clf: gpt-reserve] | \"프롬프트 테스트\"\n"
                "[2026-10-01 11:46:20] [sid: 01a0f4da-0ea0-7691-a1cb-fac895418797] ➔ [USAGE] CLASSIFIER (gpt-reserve) | input=250 output=5 tokens | loc=0 lines\n"
                "[2026-10-01 11:46:40] [sid: 01a0f4da-0ea0-7691-a1cb-fac895418797] ➔ [USAGE: PLATINUM] (gpt-6-sol) | input=66884 output=339 tokens | real_credit=0.5576 | balance=2994.15 | loc=12 lines\n"
            )

        try:
            os.environ["TIERBRIDGE_LOG_PATH"] = temp_path
            resp = client.get("/v1/dashboard/stats")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("records", data)
            records = data["records"]
            self.assertEqual(len(records), 2)
            
            # 10월 CLASSIFIER 레코드 검증
            clf_rec = records[0]
            self.assertEqual(clf_rec["month"], "2026-10")
            self.assertEqual(clf_rec["decision"], "CLASSIFIER")
            self.assertEqual(clf_rec["model"], "gpt-reserve")
            self.assertGreater(clf_rec["cost"], 0.0)

            # 10월 Main PLATINUM 레코드 검증
            main_rec = records[1]
            self.assertEqual(main_rec["month"], "2026-10")
            self.assertEqual(main_rec["session_id"], "01a0f4da-0ea0-7691-a1cb-fac895418797")
            self.assertEqual(main_rec["decision"], "PLATINUM")
            self.assertEqual(main_rec["model"], "gpt-6-sol")
            self.assertEqual(main_rec["real_credit"], 0.5576)
            self.assertEqual(main_rec["balance"], 2994.15)
            self.assertEqual(main_rec["loc"], 12)
            self.assertGreater(main_rec["cost"], 0.0)
        finally:
            if "TIERBRIDGE_LOG_PATH" in os.environ:
                del os.environ["TIERBRIDGE_LOG_PATH"]
            if os.path.exists(temp_path):
                os.remove(temp_path)

if __name__ == "__main__":
    unittest.main()
