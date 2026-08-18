import os
import sys
import unittest
import asyncio
from unittest.mock import AsyncMock, patch

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
        sample_log_line = "[2026-08-18 16:45:00] [sid: sess_test1] ➔ [USAGE: GOLD] (gpt-5.6-terra) | input=2500 output=450 tokens | real_credit=0.1524 | balance=1380.15 | loc=35 lines | cost=$0.030480 USD"
        
        usage_pattern = analyze_usage.re.compile(
            r"^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[USAGE(?::\s*(?P<decision_opt>[^\]]+))?\](?:\s+(?P<decision_legacy>[^\s(]+))?\s+\((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| real_credit=(?P<real_credit>[\d\.]+))?(?: \| balance=(?P<balance>[\d\.]+))?(?: \| loc=(?P<loc>\d+) lines)? \| cost=\$(?P<cost>[\d\.]+) USD"
        )
        
        m = usage_pattern.search(sample_log_line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("sid"), "sess_test1")
        self.assertEqual(m.group("decision_opt"), "GOLD")
        self.assertEqual(m.group("model"), "gpt-5.6-terra")
        self.assertEqual(m.group("in_tok"), "2500")
        self.assertEqual(m.group("out_tok"), "450")
        self.assertEqual(m.group("real_credit"), "0.1524")
        self.assertEqual(m.group("balance"), "1380.15")
        self.assertEqual(m.group("loc"), "35")
        self.assertEqual(m.group("cost"), "0.030480")

if __name__ == "__main__":
    unittest.main()
