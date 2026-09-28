from datetime import datetime
from typing import Dict, Any, Tuple, Optional
from tierbridge.classifier.interfaces import ClassificationContext, StageDecision
from tierbridge.classifier.policy_manager import ClassifierPolicyManager
from tierbridge.classifier.stages.fast_path import FastPathStage
from tierbridge.classifier.stages.context_metrics import ContextMetricsStage
from tierbridge.classifier.stages.escalation import EscalationStage
from tierbridge.classifier.stages.budget_governor import BudgetGovernorStage
from tierbridge.classifier.stages.deep_path import DeepPathStage

class ClassifierPipeline:
    """
    SOLID DIP/OCP: 5단계 하이브리드 분류 파이프라인 조율자 (Orchestrator)
    """
    _instance: Optional['ClassifierPipeline'] = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ClassifierPipeline, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 의존성 주입 (Stages)
        self.fast_path_stage = FastPathStage()
        self.context_metrics_stage = ContextMetricsStage()
        self.escalation_stage = EscalationStage()
        self.budget_governor_stage = BudgetGovernorStage()
        self.deep_path_stage = DeepPathStage()

        # 텔레메트리 메트릭
        self.telemetry = {
            "total_requests": 0,
            "fast_path_hits": 0,
            "deep_path_hits": 0,
            "escalation_hits": 0,
            "budget_clamp_hits": 0,
            "current_governor_mode": "BALANCED",
            "last_classified_at": None,
            "last_stage_used": None,
            "last_classifier_model": "gpt-reserve"
        }

    TIER_RANKS = {
        "BRONZE": 1,
        "SILVER": 2,
        "GOLD": 3,
        "PLATINUM": 4,
        "DIAMOND": 5,
        "CHALLENGER": 6
    }

    async def classify(self, ctx: ClassificationContext) -> Tuple[str, str, Dict[str, Any]]:
        """
        5단계 하이브리드 파이프라인 실행:
        Returns: (final_tier, classifier_model_used, telemetry_meta)
        """
        self.telemetry["total_requests"] += 1
        self.telemetry["last_classified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        policy = ClassifierPolicyManager.load_policy()

        # 1단계: Fast-Path 판정 (0ms, $0 토큰 소모)
        fast_decision = await self.fast_path_stage.evaluate(ctx, policy)
        if fast_decision and fast_decision.handled:
            self.telemetry["fast_path_hits"] += 1
            self.telemetry["last_stage_used"] = "fast_path"
            self.telemetry["last_classifier_model"] = "fast-path-regex"
            return fast_decision.tier, "fast-path-regex", {
                "stage": "fast_path",
                "reason": fast_decision.reason,
                "confidence": fast_decision.confidence,
                "escalated": False
            }

        # 2단계: Deep-Path (LLM 심층 의미 판정)
        self.telemetry["deep_path_hits"] += 1
        deep_decision = await self.deep_path_stage.evaluate(ctx, policy)
        current_tier = deep_decision.tier or "BRONZE"
        model_used = deep_decision.metadata.get("classifier_model_used", "gpt-reserve")
        self.telemetry["last_classifier_model"] = model_used

        meta = {
            "base_tier": current_tier,
            "stage": "deep_path",
            "model_used": model_used,
            "escalated": False,
            "governor_clamped": False
        }

        # 3단계: 컨텍스트 규모 (Context Metrics Floor 적용)
        cm_decision = await self.context_metrics_stage.evaluate(ctx, policy)
        if cm_decision and cm_decision.tier:
            if self.TIER_RANKS.get(cm_decision.tier, 0) > self.TIER_RANKS.get(current_tier, 0):
                meta["context_floor_applied"] = f"{current_tier} -> {cm_decision.tier}"
                meta["context_reason"] = cm_decision.reason
                current_tier = cm_decision.tier

        # 4단계: 에러 피드백 기반 자동 승격 (Auto-Escalation)
        esc_decision = await self.escalation_stage.evaluate(ctx, policy)
        if esc_decision:
            steps = esc_decision.metadata.get("escalation_steps", 1)
            promoted_tier = EscalationStage.escalate_tier(current_tier, steps)
            if promoted_tier != current_tier:
                self.telemetry["escalation_hits"] += 1
                meta["escalated"] = True
                meta["escalated_from"] = current_tier
                meta["escalation_reason"] = esc_decision.reason
                current_tier = promoted_tier

        # 5단계: 예산 거버너 (Budget Governor Ceiling 적용)
        bg_decision = await self.budget_governor_stage.evaluate(ctx, policy)
        if bg_decision:
            self.telemetry["current_governor_mode"] = bg_decision.governor_mode or "BALANCED"
            if bg_decision.tier:
                clamped_tier = BudgetGovernorStage.apply_ceiling(current_tier, bg_decision.tier)
                if clamped_tier != current_tier:
                    self.telemetry["budget_clamp_hits"] += 1
                    meta["governor_clamped"] = True
                    meta["clamped_from"] = current_tier
                    meta["clamp_reason"] = bg_decision.reason
                    current_tier = clamped_tier

        self.telemetry["last_stage_used"] = "deep_path_escalated" if meta["escalated"] else "deep_path"
        return current_tier, model_used, meta

    def get_telemetry(self) -> Dict[str, Any]:
        total = self.telemetry["total_requests"]
        fp = self.telemetry["fast_path_hits"]
        fp_ratio = round((fp / total * 100.0), 1) if total > 0 else 0.0
        return {
            **self.telemetry,
            "fast_path_ratio_percent": fp_ratio
        }
