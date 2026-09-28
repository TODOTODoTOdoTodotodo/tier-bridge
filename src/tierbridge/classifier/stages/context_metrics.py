import re
from typing import Dict, Any, Optional
from tierbridge.classifier.interfaces import IClassifierStage, ClassificationContext, StageDecision

class ContextMetricsStage(IClassifierStage):
    """
    Stage 2: 물리적 컨텍스트 규모 및 파일 수정 범위 기반 바닥 티어(Floor) 산출
    """
    TIER_RANKS = {
        "BRONZE": 1,
        "SILVER": 2,
        "GOLD": 3,
        "PLATINUM": 4,
        "DIAMOND": 5,
        "CHALLENGER": 6
    }

    @staticmethod
    def strip_injected_memory(text: str) -> str:
        if not text:
            return ""
        # Giyeok 장기기억 주입 블록 제거
        cleaned = re.sub(r"---?\s*\[🧠\s*Giyeok.*?\][\s\S]*$", "", text, flags=re.DOTALL)
        return cleaned.strip()

    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> Optional[StageDecision]:
        cm_config = policy.get("context_metrics", {})
        if not cm_config.get("enabled", True):
            return None

        large_tok_thresh = cm_config.get("large_context_tokens", 32000)
        multi_file_thresh = cm_config.get("multi_file_count_threshold", 3)
        large_context_min = cm_config.get("large_context_min_tier", "GOLD")
        multi_file_min = cm_config.get("multi_file_min_tier", "PLATINUM")

        detected_min_tier = None
        reasons = []

        # 1. 입력 토큰 규모 평가
        if ctx.total_input_tokens >= large_tok_thresh:
            detected_min_tier = large_context_min
            reasons.append(f"large context ({ctx.total_input_tokens} tokens >= {large_tok_thresh})")

        # 2. 현재 턴 프롬프트 내 다중 파일 수정/참조 패턴 정밀 평가 (히스토리 누적 오염 방지)
        eval_texts = []
        if ctx.target_eval_prompt:
            eval_texts.append(self.strip_injected_memory(ctx.target_eval_prompt))
        if ctx.user_prompt:
            eval_texts.append(self.strip_injected_memory(ctx.user_prompt))
        if ctx.unified_request.messages and ctx.unified_request.messages[-1].content:
            # 현재 턴의 최신 1개 메시지만 포함하여 검사 (이전 히스토리 누적 메시지들은 완전 배제)
            eval_texts.append(self.strip_injected_memory(ctx.unified_request.messages[-1].content))

        turn_text = " ".join(eval_texts)
        file_patterns = re.findall(r"[\w\-\./]+\.(?:py|js|ts|java|go|rs|cpp|c|html|css|json|yaml|yml|md)", turn_text, re.IGNORECASE)
        unique_files = set(file_patterns)
        if len(unique_files) >= multi_file_thresh:
            # multi_file_min 티어와 비교하여 더 높은 티어로 설정
            if not detected_min_tier or self.TIER_RANKS.get(multi_file_min, 0) > self.TIER_RANKS.get(detected_min_tier, 0):
                detected_min_tier = multi_file_min
            reasons.append(f"multi-file scope ({len(unique_files)} files >= {multi_file_thresh})")

        if detected_min_tier:
            return StageDecision(
                handled=False,  # floor 역할이므로 파이프라인 지속
                tier=detected_min_tier,
                stage_name="context_metrics",
                reason=", ".join(reasons),
                confidence=0.85,
                metadata={"unique_files_count": len(unique_files), "input_tokens": ctx.total_input_tokens}
            )

        return None
