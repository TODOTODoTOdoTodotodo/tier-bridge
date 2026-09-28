import unittest
from tierbridge.official_pricing_crawler import OfficialPricingCrawler
from tierbridge.healing_engine import HealingEngine

class TestOfficialPricingCrawler(unittest.TestCase):
    def test_sync_prices_live_or_cache(self):
        result = OfficialPricingCrawler.sync_prices(force=True)
        self.assertTrue(result["success"])
        self.assertIn("prices", result)
        prices = result["prices"]
        self.assertIn("gpt-6-luna", prices)
        self.assertIn("gpt-6-sol", prices)
        
        # 공식 단가 검증
        self.assertEqual(prices["gpt-6-luna"]["input_price"], 0.1)
        self.assertEqual(prices["gpt-6-luna"]["output_price"], 0.5)
        self.assertEqual(prices["gpt-6-sol"]["input_price"], 2.0)
        self.assertEqual(prices["gpt-6-sol"]["output_price"], 10.0)

    def test_get_price_lookup(self):
        in_p, out_p = OfficialPricingCrawler.get_price("gpt-6-luna")
        self.assertEqual(in_p, 0.1)
        self.assertEqual(out_p, 0.5)

        in_p, out_p = OfficialPricingCrawler.get_price("gpt-6-sol")
        self.assertEqual(in_p, 2.0)
        self.assertEqual(out_p, 10.0)

        # 없는 모델 fallback
        in_p, out_p = OfficialPricingCrawler.get_price("unknown-model", fallback_in=9.9, fallback_out=19.9)
        self.assertEqual(in_p, 9.9)
        self.assertEqual(out_p, 19.9)

    def test_healing_engine_incorporates_official_pricing(self):
        status = HealingEngine.get_healing_status()
        self.assertIn("official_pricing", status)
        comparison = status["comparison"]
        
        # BRONZE (luna) 단가 확인
        bronze_row = next(r for r in comparison if r["tier"] == "BRONZE")
        self.assertEqual(bronze_row["healing_model"], "gpt-6-luna")
        self.assertEqual(bronze_row["healing_in_price"], 0.1)
        self.assertEqual(bronze_row["healing_out_price"], 0.5)

        # CHALLENGER (sol) 단가 확인
        chal_row = next(r for r in comparison if r["tier"] == "CHALLENGER")
        self.assertEqual(chal_row["healing_model"], "gpt-6-sol")
        self.assertEqual(chal_row["healing_in_price"], 2.0)
        self.assertEqual(chal_row["healing_out_price"], 10.0)

if __name__ == "__main__":
    unittest.main()
