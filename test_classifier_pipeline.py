import unittest
from tierbridge.models import UnifiedRequest, Message
from tierbridge.classifier.interfaces import ClassificationContext
from tierbridge.classifier.policy_manager import ClassifierPolicyManager
from tierbridge.classifier.stages.fast_path import FastPathStage
from tierbridge.classifier.stages.context_metrics import ContextMetricsStage
from tierbridge.classifier.stages.escalation import EscalationStage
from tierbridge.classifier.stages.budget_governor import BudgetGovernorStage
from tierbridge.classifier.pipeline import ClassifierPipeline

class TestClassifierPipeline(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.policy = ClassifierPolicyManager.load_policy()

    async def test_fast_path_simple_pattern(self):
        stage = FastPathStage()
        req = UnifiedRequest(model="gpt-6-luna", messages=[Message(role="user", content="git status")])
        ctx = ClassificationContext(
            unified_request=req,
            user_prompt="git status",
            is_new_user_turn=True,
            substep_prompt="git status",
            target_eval_prompt="git status"
        )
        decision = await stage.evaluate(ctx, self.policy)
        self.assertIsNotNone(decision)
        self.assertTrue(decision.handled)
        self.assertEqual(decision.tier, "BRONZE")
        self.assertEqual(decision.stage_name, "fast_path")

    async def test_fast_path_complex_query_falls_through(self):
        stage = FastPathStage()
        complex_prompt = "Spring Boot JPA에서 다중 데이터소스 트랜잭션 매니저를 분리하여 분산 트랜잭션 및 데드락을 해결해줘"
        req = UnifiedRequest(model="gpt-6-luna", messages=[Message(role="user", content=complex_prompt)])
        ctx = ClassificationContext(
            unified_request=req,
            user_prompt=complex_prompt,
            is_new_user_turn=True,
            substep_prompt=complex_prompt,
            target_eval_prompt=complex_prompt
        )
        decision = await stage.evaluate(ctx, self.policy)
        self.assertIsNone(decision)

    async def test_context_metrics_floor(self):
        stage = ContextMetricsStage()
        req = UnifiedRequest(
            model="gpt-6-luna", 
            messages=[
                Message(role="user", content="Controller.java, Service.java, Repository.java, Entity.java 파일들을 확인해줘")
            ]
        )
        ctx = ClassificationContext(
            unified_request=req,
            user_prompt="파일 수정",
            is_new_user_turn=True,
            substep_prompt="파일 수정",
            target_eval_prompt="파일 수정",
            total_input_tokens=40000  # > 32k large context
        )
        decision = await stage.evaluate(ctx, self.policy)
        self.assertIsNotNone(decision)
        # 4 files referenced -> PLATINUM floor
        self.assertEqual(decision.tier, "PLATINUM")
        self.assertFalse(decision.handled)

    async def test_escalation_error_keywords(self):
        stage = EscalationStage()
        req = UnifiedRequest(
            model="gpt-6-luna",
            messages=[
                Message(role="user", content="코드 실행해줘"),
                Message(role="assistant", content="Traceback (most recent call last): NullPointerException failed!"),
                Message(role="user", content="다시 수정해줘")
            ]
        )
        ctx = ClassificationContext(
            unified_request=req,
            user_prompt="다시 수정해줘",
            is_new_user_turn=True,
            substep_prompt="다시 수정해줘",
            target_eval_prompt="다시 수정해줘"
        )
        decision = await stage.evaluate(ctx, self.policy)
        self.assertIsNotNone(decision)
        self.assertGreaterEqual(decision.metadata.get("escalation_steps", 0), 1)

    async def test_budget_governor_clamp(self):
        stage = BudgetGovernorStage()
        req = UnifiedRequest(model="gpt-6-sol", messages=[Message(role="user", content="테스트")])
        
        # 1. Critical mode (< 5%)
        ctx_crit = ClassificationContext(
            unified_request=req,
            user_prompt="테스트",
            is_new_user_turn=True,
            substep_prompt="테스트",
            target_eval_prompt="테스트",
            credit_remaining_percent=3.5
        )
        dec_crit = await stage.evaluate(ctx_crit, self.policy)
        self.assertEqual(dec_crit.governor_mode, "CRITICAL")
        self.assertEqual(dec_crit.tier, "BRONZE")

        # 2. Eco mode (< 20%)
        ctx_eco = ClassificationContext(
            unified_request=req,
            user_prompt="테스트",
            is_new_user_turn=True,
            substep_prompt="테스트",
            target_eval_prompt="테스트",
            credit_remaining_percent=15.0
        )
        dec_eco = await stage.evaluate(ctx_eco, self.policy)
        self.assertEqual(dec_eco.governor_mode, "ECO")
        self.assertEqual(dec_eco.tier, "GOLD")

    async def test_full_pipeline_fast_path(self):
        pipeline = ClassifierPipeline()
        req = UnifiedRequest(model="gpt-6-luna", messages=[Message(role="user", content="ls")])
        ctx = ClassificationContext(
            unified_request=req,
            user_prompt="ls",
            is_new_user_turn=True,
            substep_prompt="ls",
            target_eval_prompt="ls"
        )
        tier, model, meta = await pipeline.classify(ctx)
        self.assertEqual(tier, "BRONZE")
        self.assertEqual(model, "fast-path-regex")
        self.assertEqual(meta["stage"], "fast_path")

if __name__ == "__main__":
    unittest.main()
