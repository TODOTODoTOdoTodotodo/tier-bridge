import unittest
from unittest.mock import patch
from tierbridge.healing_engine import HealingEngine

class TestHealingEngineUpstream(unittest.TestCase):
    def test_dynamic_recommendation_gpt6_detected(self):
        mock_upstream_models = [
            {"slug": "gpt-6-sol", "display_name": "GPT-6-Sol"},
            {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna"},
            {"slug": "gpt-5.6-terra", "display_name": "GPT-5.6-Terra"}
        ]
        active_mapping_gpt56 = {
            "BRONZE": {"model": "gpt-5.6-luna", "effort": "low", "input_price": 1.0, "output_price": 3.0},
            "SILVER": {"model": "gpt-5.6-luna", "effort": "medium", "input_price": 1.0, "output_price": 3.0},
            "GOLD": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.5, "output_price": 10.0},
            "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
            "DIAMOND": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
            "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 5.0, "output_price": 20.0}
        }
        rec = HealingEngine.get_dynamic_recommendation(
            upstream_models=mock_upstream_models,
            active_mapping=active_mapping_gpt56,
            active_vid="v1.0.0"
        )
        self.assertTrue(rec["has_new_healing"])
        self.assertEqual(rec["version_id"], "v2.0.0-gpt6-hotpatch")
        self.assertEqual(rec["mapping"]["BRONZE"]["model"], "gpt-6-luna")
        self.assertEqual(rec["mapping"]["CHALLENGER"]["model"], "gpt-6-sol")

    def test_dynamic_recommendation_already_gpt6(self):
        mock_upstream_models = [
            {"slug": "gpt-6-sol", "display_name": "GPT-6-Sol"},
            {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna"}
        ]
        active_mapping_gpt6 = {
            "BRONZE": {"model": "gpt-6-luna", "effort": "low", "input_price": 0.5, "output_price": 1.5},
            "SILVER": {"model": "gpt-6-luna", "effort": "medium", "input_price": 0.5, "output_price": 1.5},
            "GOLD": {"model": "gpt-6-sol", "effort": "low", "input_price": 2.0, "output_price": 8.0},
            "PLATINUM": {"model": "gpt-6-sol", "effort": "medium", "input_price": 2.0, "output_price": 8.0},
            "DIAMOND": {"model": "gpt-6-sol", "effort": "high", "input_price": 2.0, "output_price": 8.0},
            "CHALLENGER": {"model": "gpt-6-sol", "effort": "xhigh", "input_price": 2.0, "output_price": 8.0}
        }
        rec = HealingEngine.get_dynamic_recommendation(
            upstream_models=mock_upstream_models,
            active_mapping=active_mapping_gpt6,
            active_vid="v2.0.0-gpt6-hotpatch"
        )
        self.assertFalse(rec["has_new_healing"])

    def test_get_healing_status_structure(self):
        status = HealingEngine.get_healing_status()
        self.assertIn("has_new_healing", status)
        self.assertIn("comparison", status)
        self.assertIn("dynamic_proposal", status)
        self.assertEqual(len(status["comparison"]), 6)
        for row in status["comparison"]:
            self.assertIn("savings_pct", row)
            self.assertIn("current_model", row)
            self.assertIn("healing_model", row)

if __name__ == "__main__":
    unittest.main()
