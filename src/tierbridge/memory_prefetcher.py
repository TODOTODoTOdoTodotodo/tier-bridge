"""
MemoryPrefetcher: Step 2 사전 기억 회수(Pre-fetch Recall) & 50ms Strict 타임아웃 샌드박싱 모듈

사용자가 새로운 프롬프트를 전송했을 때, 업스트림 LLM으로 전달하기 직전
~/.tierbridge/memory.db 장기 기억저장소에서 과거 유사 문제 해결책(정답 코드/아키텍처 결정)을
5ms 이내로 회수하여 인바운드 프롬프트 컨텍스트에 안전하게 선행 주입(Soft Reference)합니다.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("TierBridge.MemoryPrefetcher")


class MemoryPrefetcher:
    """
    사전 기억 회수 및 50ms Strict 타임아웃 샌드박스 핸들러
    """

    TIMEOUT_SEC = 0.050    # 50ms Strict Limit (사용자 TTFT 지연 원천 차단)
    MAX_CHAR_LIMIT = 1000  # 약 300~500 토큰 캡핑 (컨텍스트 오염 방지)
    MIN_SIMILARITY_THRESHOLD = 0.60  # 핵심 지식 최소 적합도 임계치 (60% 이상 즉시 브리핑)
    HINT_SIMILARITY_THRESHOLD = 0.35  # 보조 힌트 최소 적합도 임계치 (35% 이상 제안형 힌트)

    @classmethod
    def format_soft_reference_block(
        cls,
        memories: List[Dict[str, Any]],
        hints: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        사용자 회상 질문에 신속하게 응답하고 잠재 연관 지식 힌트를 함께 제안하는 지식 블록 생성
        """
        lines = [
            "[🧠 Giyeok 장기 기억저장소 연관 지식]",
            "아래 내용은 과거 세션에서 실제로 해결/작업했던 검증된 히스토리입니다.",
            "1. 사용자가 과거 기억/이력에 대해 묻는 경우 ('기억나는거 있어?', '어떻게 작업했지?' 등):",
            "   👉 전체 파일/Git을 다시 검색(rg/git)하지 말고, 아래 지식을 최우선으로 인용하여 '이러한 작업이 진행된 적이 있습니다. 더 상세한 내용이나 추가 작업이 필요하신가요?' 형태로 신속하게 브리핑하세요.",
            "2. 새로운 코드 구현/수정 요청인 경우:",
            "   👉 아래 적용 해결책을 검증된 베스트 프랙티스로 적극 참고하여 반영하세요.",
            ""
        ]

        # 1. 고적합도 핵심 지식 (High Confidence)
        if memories:
            for idx, m in enumerate(memories, 1):
                prob = (m.get("problem") or "").strip().replace("\n", " ")
                sol = (m.get("solution") or "").strip()
                score_pct = int(m.get("score", 0.95) * 100)
                lines.append(f"### [참고 사례 #{idx}] (적합도: {score_pct}%)")
                lines.append(f"- 📌 과거 문제: {prob}")
                lines.append(f"- 💡 적용 해결책:\n{sol}")
                lines.append("")

        # 2. 보조 힌트 지식 (Low Score / Exploratory Hints)
        if hints:
            for idx, h in enumerate(hints, 1):
                prob = (h.get("problem") or "").strip().replace("\n", " ")
                sol = (h.get("solution") or "").strip()
                sol_snippet = sol[:120].replace("\n", " ") + "..." if len(sol) > 120 else sol
                score_pct = int(h.get("score", 0.45) * 100)
                lines.append(f"### [💡 보조 참고 힌트 #{idx}] (적합도: {score_pct}%)")
                lines.append(f"- 📌 관련 가능성이 있는 과거 작업: {prob}")
                lines.append(f"- 💡 해결 요약: {sol_snippet}")
                lines.append(f"- ℹ️ 참고 지침: 직접적인 일치가 아닐 수 있으므로, 사용자에게 \"혹시 과거 '{prob[:25]}...' 작업과 관련된 것일까요?\" 형태로 가볍게 확인 제안하세요.")
                lines.append("")

        full_text = "\n".join(lines).strip()
        if len(full_text) > cls.MAX_CHAR_LIMIT:
            full_text = full_text[:cls.MAX_CHAR_LIMIT] + "\n... (이하 생략)"
        return full_text

    @classmethod
    async def fetch_associated_context(cls, user_prompt: str, current_session_id: str = "") -> Optional[str]:
        """
        50ms Strict Sandbox 내에서 연관 장기 기억 회수 및 실시간 로그 방출
        
        Args:
            user_prompt: 사용자의 현재 질문/프롬프트 텍스트
            current_session_id: 현재 활성 세션 식별자 (자기 참조 배제용)
        
        Returns:
            Optional[str]: 주입할 Soft Reference 마크다운 텍스트 블록 (없으면 None)
        """
        if not user_prompt or len(user_prompt.strip()) < 5:
            return None

        p_clean = user_prompt.strip()

        # 서브스텝 / 단순 진행 보고는 회수 트리거 제외 (노이즈 방어)
        if p_clean.startswith("[Substep]") or "[이전 대화 요약" in p_clean:
            return None

        # 단순 명령어 / 상태 확인 질의는 기억 회수 제외 (Bypass)
        p_lower = p_clean.lower()
        if any(p_lower.startswith(cmd) for cmd in ["git ", "npm ", "yarn ", "pnpm ", "mvn ", "gradle ", "docker ", "kubectl ", "ls", "pwd", "clear", "echo "]):
            if not any(k in p_lower for k in ["기억", "이력", "히스토리", "과거", "작업한", "어떻게 했"]):
                return None

        try:
            from tierbridge.memory_handler import MemoryHandler

            # 50ms Strict 타임아웃 샌드박싱 실행 (<5ms 일반 실행)
            results = await asyncio.wait_for(
                asyncio.to_thread(MemoryHandler.search_associated_memories, query=p_clean[:200], limit=4),
                timeout=cls.TIMEOUT_SEC
            )

            # 현재 세션 직전 턴 자기 참조 배제 및 적합도 구간별 선별
            valid_memories = []
            hint_memories = []
            for r in (results or []):
                r_sid = r.get("session_id", "")
                r_score = r.get("score", 0.0)
                # 현재 세션의 데이터는 중복 주입 방지를 위해 배제 (단, default 세션 제외)
                if current_session_id and r_sid and r_sid == current_session_id:
                    continue
                if r_score >= cls.MIN_SIMILARITY_THRESHOLD:
                    valid_memories.append(r)
                elif r_score >= cls.HINT_SIMILARITY_THRESHOLD:
                    hint_memories.append(r)

            if valid_memories or hint_memories:
                top_m = valid_memories[0] if valid_memories else hint_memories[0]
                prob_snippet = (top_m.get("problem") or "")[:35].replace("\n", " ")
                sol_snippet = (top_m.get("solution") or "")[:35].replace("\n", " ")
                score_pct = int(top_m.get("score", 0.95) * 100)
                m_id = str(top_m.get("id", ""))[:8]

                # 실시간 하네스 로그 방출
                log_tag = "RECALLED" if valid_memories else "HINT"
                print(f"➔ [MEMORY:{log_tag}] (Score: {score_pct}%, ID: {m_id}) 📌 '{prob_snippet}...' 💡 '{sol_snippet}...'", flush=True)

                return cls.format_soft_reference_block(valid_memories[:2], hint_memories[:2])
            else:
                p_summary = p_clean.replace("\n", " ")[:30]
                print(f"➔ [MEMORY:RECALL_NONE] No associated memory found | query='{p_summary}...'", flush=True)
                return None

        except asyncio.TimeoutError:
            print("➔ [MEMORY:RECALL_TIMEOUT] Memory Prefetch timed out (>50ms). Fallback to original prompt.", flush=True)
            return None
        except Exception as e:
            logger.debug(f"[MemoryPrefetcher] Recall failed safely: {e}")
            return None
