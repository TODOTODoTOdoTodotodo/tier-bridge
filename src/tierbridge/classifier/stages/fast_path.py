import re
from typing import Dict, Any, Optional
from tierbridge.classifier.interfaces import IClassifierStage, ClassificationContext, StageDecision

class FastPathStage(IClassifierStage):
    """
    Stage 1: 정적/규칙 기반 초고속 0ms 패스 (LLM 호출 비용 및 지연 0)
    """
    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> Optional[StageDecision]:
        fp_config = policy.get("fast_path", {})
        if not fp_config.get("enabled", True):
            return None

        prompt = ctx.target_eval_prompt.strip()
        if not prompt:
            return StageDecision(
                handled=True,
                tier="BRONZE",
                stage_name="fast_path",
                reason="Empty prompt defaults to BRONZE",
                confidence=1.0
            )

        max_len = fp_config.get("max_token_length", 150)
        # 대략적인 토큰 수 추정 (단어/글자 기반)
        if len(prompt) > max_len * 4:
            return None

        patterns = fp_config.get("simple_patterns", [])
        for pattern in patterns:
            try:
                if re.search(pattern, prompt, re.IGNORECASE):
                    default_tier = fp_config.get("default_tier", "BRONZE")
                    return StageDecision(
                        handled=True,
                        tier=default_tier,
                        stage_name="fast_path",
                        reason=f"Matched fast-path pattern: {pattern}",
                        confidence=0.95
                    )
            except Exception:
                continue

        return None
