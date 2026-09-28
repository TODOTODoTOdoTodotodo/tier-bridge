import re
from typing import Dict, Any, Optional
from tierbridge.classifier.interfaces import IClassifierStage, ClassificationContext, StageDecision

class EscalationStage(IClassifierStage):
    """
    Stage 3: 직전 턴 에러 및 실패 감지 기반 자동 티어 승격 (Auto-Escalation)
    """
    TIER_SEQUENCE = ["BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND", "CHALLENGER"]

    @staticmethod
    def strip_injected_memory(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"---?\s*\[🧠\s*Giyeok.*?\][\s\S]*$", "", text, flags=re.DOTALL).strip()

    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> Optional[StageDecision]:
        esc_config = policy.get("escalation", {})
        if not esc_config.get("enabled", True):
            return None

        messages = ctx.unified_request.messages
        if len(messages) < 2:
            return None

        error_keywords = esc_config.get("error_keywords", ["error", "exception", "failed", "traceback"])
        max_steps = esc_config.get("max_escalation_steps", 1)

        # 직전 2개 메시지 검사 (직전 응답 및 에러 리포트 대상, 주입된 장기기억 제외)
        cleaned_contents = []
        for m in messages[-2:]:
            if m.content:
                cleaned_contents.append(self.strip_injected_memory(m.content).lower())
        recent_texts = " ".join(cleaned_contents)

        detected_errors = []
        for kw in error_keywords:
            kw_clean = kw.lower()
            # 영문 키워드는 단어 경계(\b) 적용, 한글은 부분 매칭 적용
            if re.search(r"^[a-z_]+$", kw_clean):
                if re.search(r"\b" + re.escape(kw_clean) + r"\b", recent_texts):
                    detected_errors.append(kw)
            else:
                if kw_clean in recent_texts:
                    detected_errors.append(kw)

        if detected_errors:
            steps = min(len(detected_errors), max_steps)
            return StageDecision(
                handled=False,
                stage_name="escalation",
                reason=f"Detected error feedback: {', '.join(detected_errors[:3])}",
                confidence=0.90,
                metadata={"escalation_steps": steps, "detected_errors": detected_errors[:5]}
            )

        return None

    @classmethod
    def escalate_tier(cls, current_tier: str, steps: int = 1) -> str:
        try:
            curr_idx = cls.TIER_SEQUENCE.index(current_tier)
            new_idx = min(len(cls.TIER_SEQUENCE) - 1, curr_idx + steps)
            return cls.TIER_SEQUENCE[new_idx]
        except ValueError:
            return current_tier
