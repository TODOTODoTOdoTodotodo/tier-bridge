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
    MIN_SIMILARITY_THRESHOLD = 0.70  # 최소 적합도 임계치 (70% 미만 자동 탈락)

    @classmethod
    def format_soft_reference_block(cls, memories: List[Dict[str, Any]]) -> str:
        """
        오답 주입을 방어하고 현재 컨텍스트를 최우선하도록 유도하는 Soft Reference 템플릿 생성
        """
        lines = [
            "[🧠 Giyeok 장기 기억저장소 참고 지식]",
            "⚠️ 아래 내용은 과거 세션에서 해결했던 유사 사례 히스토리입니다.",
            "현재 사용자의 최신 요구사항 및 코드베이스 상태와 상충되거나 맞지 않는 경우, 이 참고 지식을 무시하고 [현재 프롬프트와 파일 상태]를 절대 최우선으로 적용하세요.",
            ""
        ]
        for idx, m in enumerate(memories, 1):
            prob = (m.get("problem") or "").strip().replace("\n", " ")
            sol = (m.get("solution") or "").strip()
            score_pct = int(m.get("score", 0.95) * 100)
            lines.append(f"### [참고 사례 #{idx}] (적합도: {score_pct}%)")
            lines.append(f"- 📌 과거 문제: {prob}")
            lines.append(f"- 💡 적용 해결책:\n{sol}")
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

        try:
            from tierbridge.memory_handler import MemoryHandler

            # 50ms Strict 타임아웃 샌드박싱 실행 (<5ms 일반 실행)
            results = await asyncio.wait_for(
                asyncio.to_thread(MemoryHandler.search_associated_memories, query=p_clean[:200], limit=2),
                timeout=cls.TIMEOUT_SEC
            )

            # 현재 세션 직전 턴 자기 참조 배제 & 70% 이상 고유사도 에피소드만 선별
            valid_memories = []
            for r in (results or []):
                r_sid = r.get("session_id", "")
                r_score = r.get("score", 0.0)
                # 현재 세션의 데이터는 중복 주입 방지를 위해 배제 (단, default 세션 제외)
                if current_session_id and r_sid and r_sid == current_session_id:
                    continue
                if r_score >= cls.MIN_SIMILARITY_THRESHOLD:
                    valid_memories.append(r)

            if valid_memories:
                top_m = valid_memories[0]
                prob_snippet = (top_m.get("problem") or "")[:35].replace("\n", " ")
                sol_snippet = (top_m.get("solution") or "")[:35].replace("\n", " ")
                score_pct = int(top_m.get("score", 0.95) * 100)
                m_id = str(top_m.get("id", ""))[:8]

                # 실시간 하네스 로그 방출
                print(f"➔ [MEMORY:RECALLED] (Score: {score_pct}%, ID: {m_id}) 📌 '{prob_snippet}...' 💡 '{sol_snippet}...'", flush=True)

                return cls.format_soft_reference_block(valid_memories[:2])
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
