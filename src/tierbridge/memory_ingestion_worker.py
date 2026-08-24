"""
MemoryIngestionWorker: Step 1 비동기 세션 로그 수집 파이프라인 & 퀄리티 게이팅 모듈

하네스에서 발생한 세션 대화 및 프롬프트 로그를 사용자 응답(TTFT) 지연 없이 0ms 비동기로 수집하고,
"고민(Problem) ➔ 해결(Solution) ➔ 결과(Outcome)"의 고품질 3단 에피소드로 구조화하여
sub-memory-bootstrap (Giyeok) 장기 기억 저장소(SQLite / sqlite-vec)에 인프로세스 직접 적재합니다.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("TierBridge.MemoryIngestion")


class MemoryIngestionWorker:
    """
    TierBridge 세션 로그 비동기 수집 및 퀄리티 게이트 워커
    """

    @classmethod
    def format_problem_solution_episode(
        cls,
        session_id: str,
        prompt: str,
        decision: str,
        loc: int,
        cost: float
    ) -> str:
        """
        사용자의 고민과 시스템의 해결 결정을 3단 지식 포맷으로 표준화
        """
        clean_prompt = prompt.strip()
        return (
            f"[Session: {session_id}] [Decision: {decision}] [LOC: {loc}] [Cost: ${cost:.4f}]\n"
            f"- 📌 문제 및 요구사항: {clean_prompt}\n"
            f"- 💡 적용 등급 및 라우팅: {decision}\n"
            f"- 🏷️ 태그: #{decision} #Session_{session_id[:8]} #TierBridge"
        )

    @classmethod
    def should_ingest(cls, decision: str, loc: int, is_first_turn: bool, prompt: str) -> bool:
        """
        CPU 룰 기반 1차 퀄리티 게이트 필터링 (비용 $0.00)
        - BRONZE 단순 스텝이면서 코드 수정(LOC)이 없고 첫 턴이 아닌 경우 배제 (노이즈 방어)
        - 빈 프롬프트 또는 5자 미만 초단문 배제
        """
        if not prompt or len(prompt.strip()) < 5:
            return False

        # BRONZE 단순 스크립트 실행/파일 조회 턴은 배제하되, 사용자의 첫 질문이거나 실제 코드를 수정한 경우 통과
        if decision.upper() == "BRONZE" and loc == 0 and not is_first_turn:
            return False

        return True

    @classmethod
    async def process_log_event(cls, event: Dict[str, Any]) -> bool:
        """
        비동기 인프로세스 기억 저장 실행 (Non-blocking, <5ms)
        
        Args:
            event: 세션 이벤트 메타데이터 딕셔너리
                   - session_id: 세션 고유 식별자
                   - prompt: 사용자/에이전트 프롬프트 내용
                   - decision: 모델 라우팅 등급 (GOLD, SILVER, BRONZE, etc.)
                   - loc: 생성/수정된 코드 라인 수
                   - cost: 소모 비용 (USD)
                   - is_first_turn: 세션의 최초 질의 턴 여부
        
        Returns:
            bool: 저장 성공 여부
        """
        decision = event.get("decision", "UNKNOWN")
        loc = event.get("loc", 0)
        is_first_turn = event.get("is_first_turn", False)
        prompt = event.get("prompt", "")
        session_id = event.get("session_id", "sess_default")
        cost = event.get("cost", 0.0)

        # 1. 1차 퀄리티 게이트 필터링
        if not cls.should_ingest(decision, loc, is_first_turn, prompt):
            logger.debug(f"[MemoryIngestion] Skipped low-value turn: [{decision}] loc={loc}, first={is_first_turn}")
            return False

        # 2. 3단 지식 에피소드 콘텐츠 및 태그 생성
        content = cls.format_problem_solution_episode(session_id, prompt, decision, loc, cost)
        tags: List[str] = [session_id, decision, "tierbridge_auto_ingest"]
        if loc > 0:
            tags.append("code_modified")
        if is_first_turn:
            tags.append("initial_request")

        # 3. Direct Module In-process 임포트 및 비동기 저장 (<5ms)
        try:
            from sub_memory.service import MemoryService
            service = MemoryService()
            
            # 메인 이벤트 루프를 블로킹하지 않도록 asyncio.to_thread로 위임
            await asyncio.to_thread(service.store_memory, content=content, tags=tags)
            logger.debug(f"[MemoryIngestion] Direct Memory Store Success: {session_id} [{decision}] (LOC: {loc})")
            return True
        except ImportError:
            # sub_memory 모듈이 미설치된 환경에서도 서비스 중단 없이 안전하게 건너뜀
            logger.debug("[MemoryIngestion] sub_memory module not found. Skipping in-process storage.")
            return False
        except Exception as e:
            logger.warning(f"[MemoryIngestion] Memory store execution failed: {e}")
            return False
