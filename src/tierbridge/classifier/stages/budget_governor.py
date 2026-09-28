from typing import Dict, Any, Optional
from tierbridge.classifier.interfaces import IClassifierStage, ClassificationContext, StageDecision
from tierbridge.credit_interceptor import CreditInterceptor

class BudgetGovernorStage(IClassifierStage):
    """
    Stage 4: 실시간 기업 잔여 크레딧 연동 기반 예산 거버너 (Budget Governor)
    """
    TIER_SEQUENCE = ["BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND", "CHALLENGER"]

    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> Optional[StageDecision]:
        bg_config = policy.get("budget_governor", {})
        if not bg_config.get("enabled", True):
            return None

        # 1. 컨텍스트 또는 인터셉터에서 잔여 크레딧 비율 확인
        rem_pct = ctx.credit_remaining_percent
        if rem_pct is None:
            interceptor = CreditInterceptor()
            if interceptor.spend_limit and interceptor.spend_limit > 0 and interceptor.last_known_used is not None:
                used = interceptor.last_known_used
                limit = interceptor.spend_limit
                rem_pct = max(0.0, (1.0 - (used / limit)) * 100.0)

        if rem_pct is None:
            return None

        critical_thresh = bg_config.get("critical_threshold_percent", 5.0)
        eco_thresh = bg_config.get("eco_threshold_percent", 20.0)
        critical_ceiling = bg_config.get("critical_tier_ceiling", "BRONZE")
        eco_ceiling = bg_config.get("eco_tier_ceiling", "GOLD")

        if rem_pct <= critical_thresh:
            return StageDecision(
                handled=False,
                governor_mode="CRITICAL",
                tier=critical_ceiling,
                stage_name="budget_governor",
                reason=f"Credit remaining critical ({rem_pct:.1f}% <= {critical_thresh}%), capping to {critical_ceiling}",
                confidence=1.0,
                metadata={"remaining_percent": rem_pct}
            )
        elif rem_pct <= eco_thresh:
            return StageDecision(
                handled=False,
                governor_mode="ECO",
                tier=eco_ceiling,
                stage_name="budget_governor",
                reason=f"Credit remaining low ({rem_pct:.1f}% <= {eco_thresh}%), capping to {eco_ceiling}",
                confidence=0.95,
                metadata={"remaining_percent": rem_pct}
            )

        return StageDecision(
            handled=False,
            governor_mode="BALANCED",
            stage_name="budget_governor",
            reason=f"Credit remaining normal ({rem_pct:.1f}%)",
            confidence=0.90,
            metadata={"remaining_percent": rem_pct}
        )

    @classmethod
    def apply_ceiling(cls, current_tier: str, ceiling_tier: str) -> str:
        try:
            curr_idx = cls.TIER_SEQUENCE.index(current_tier)
            ceil_idx = cls.TIER_SEQUENCE.index(ceiling_tier)
            if curr_idx > ceil_idx:
                return ceiling_tier
            return current_tier
        except ValueError:
            return current_tier
