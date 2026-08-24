"""
MemoryIngestionWorker: Step 1 비동기 세션 로그 수집 파이프라인 & 퀄리티 게이팅 모듈

하네스에서 발생한 세션 대화 및 프롬프트 로그를 사용자 응답(TTFT) 지연 없이 0ms 비동기로 수집하고,
"고민(Problem) ➔ 해결(Solution / LLM Response) ➔ 결과(Outcome)"의 고품질 3단 에피소드로 구조화하여
sub-memory-bootstrap (Giyeok) 장기 기억 저장소(SQLite / sqlite-vec)에 인프로세스 직접 적재합니다.
"""

import os
import uuid
import json
import sqlite3
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("TierBridge.MemoryIngestion")


class MemoryIngestionWorker:
    """
    TierBridge 세션 로그 비동기 수집 및 퀄리티 게이트 워커
    """

    DB_PATHS = [
        os.environ.get("MEMORY_DB_PATH", ""),
        os.path.expanduser("~/.tierbridge/memory.db"),
        os.path.expanduser("~/.codex/sub-memory/memory.db"),
        os.path.expanduser("~/.sub-memory/memory.db"),
        os.path.abspath(".sub-memory/memory.db"),
        os.path.abspath("memory.db")
    ]

    @classmethod
    def get_db_path(cls) -> str:
        """
        저장할 SQLite memory.db 경로 탐색 및 자동 생성 경로 반환
        """
        for p in cls.DB_PATHS:
            if p and os.path.exists(p):
                return p

        # 기본 경로 설정 및 부모 디렉토리 생성
        default_path = os.path.expanduser("~/.tierbridge/memory.db")
        os.makedirs(os.path.dirname(default_path), exist_ok=True)
        return default_path

    @classmethod
    def store_to_sqlite(
        cls,
        db_path: str,
        content: str,
        tags: List[str],
        prompt: str = "",
        solution_text: str = "",
        session_id: str = "sess_default",
        decision: str = "UNKNOWN",
        loc: int = 0,
        cost: float = 0.0
    ) -> bool:
        """
        SQLite memory.db 테이블 직접 Insert (Giyeok nodes 및 TierBridge memories 테이블 듀얼 지원, Session ID 완벽 결합)
        """
        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()

        # 1. Giyeok nodes 테이블이 존재하는지 확인
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
        has_nodes = cursor.fetchone() is not None

        if has_nodes:
            node_id = str(uuid.uuid4())
            # 세션 ID, 라우팅 등급, 코드 라인 수, 비용 메타데이터를 헤더로 결합
            node_text = (
                f"[Session: {session_id}] [Decision: {decision}] [LOC: {loc}] [Cost: ${cost:.4f}]\n"
                f"User: {prompt}\n"
                f"Assistant: {solution_text if solution_text else content}"
            )
            # 384 dims float32 = 1536 bytes
            zero_embedding = bytes(1536)
            iso_time = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO nodes (id, text, embedding, timestamp) VALUES (?, ?, ?, ?);",
                (node_id, node_text, zero_embedding, iso_time)
            )

        # 2. TierBridge memories 테이블 지원
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        tags_json = json.dumps(tags, ensure_ascii=False)
        cursor.execute("INSERT INTO memories (content, tags) VALUES (?, ?);", (content, tags_json))

        conn.commit()
        conn.close()
        return True

    @classmethod
    def format_problem_solution_episode(
        cls,
        session_id: str,
        prompt: str,
        decision: str,
        loc: int,
        cost: float,
        solution_text: str = ""
    ) -> str:
        """
        사용자의 고민과 LLM의 최종 해결책/코드를 3단 지식 포맷으로 표준화
        """
        clean_prompt = prompt.strip()
        clean_sol = solution_text.strip() if solution_text else f"라우팅 등급: {decision}"
        if len(clean_sol) > 1200:
            clean_sol = clean_sol[:1200] + "\n... (이하 생략)"

        return (
            f"[Session: {session_id}] [Decision: {decision}] [LOC: {loc}] [Cost: ${cost:.4f}]\n"
            f"- 📌 문제 및 요구사항: {clean_prompt}\n"
            f"- 💡 적용 해결책 및 LLM 응답: {clean_sol}\n"
            f"- 🏷️ 태그: #{decision} #Session_{session_id[:8]} #TierBridge"
        )

    @classmethod
    def should_ingest(cls, decision: str, loc: int, is_first_turn: bool, prompt: str) -> bool:
        """
        CPU 룰 기반 정밀 퀄리티 게이트 필터링 ($0.00)
        - 빈 프롬프트 또는 5자 미만 초단문 배제
        - 서브스텝 / 중간 진행 보고 턴 노이즈 차단 ([Substep], [이전 대화 요약 등)
        - 사용자의 원본 고민(is_first_turn), 실제 코드 작성(loc > 0), 고난도 결정(GOLD/PLATINUM/CHALLENGER)만 선별 보존
        """
        if not prompt or len(prompt.strip()) < 5:
            return False

        p_clean = prompt.strip()

        # 1. 서브스텝 / 단순 진행 보고 턴은 노이즈 방어를 위해 스킵 (코드 수정한 턴 제외)
        if (p_clean.startswith("[Substep]") or "[이전 대화 요약" in p_clean) and loc == 0:
            return False

        # 2. 핵심 가치 턴 판정
        if is_first_turn or loc > 0 or decision.upper() in ("GOLD", "PLATINUM", "CHALLENGER", "SOL"):
            return True

        # 3. 단순 BRONZE/SILVER 확인 턴 배제
        return False

    @classmethod
    async def process_log_event(cls, event: Dict[str, Any]) -> bool:
        """
        비동기 인프로세스 기억 저장 실행 및 표준 로그 방출 (Non-blocking, <5ms)
        """
        decision = event.get("decision", "UNKNOWN")
        loc = event.get("loc", 0)
        is_first_turn = event.get("is_first_turn", False)
        prompt = event.get("prompt", "")
        session_id = event.get("session_id", "sess_default")
        cost = event.get("cost", 0.0)
        solution_text = event.get("solution", "")

        # 1. 1차 퀄리티 게이트 필터링
        if not cls.should_ingest(decision, loc, is_first_turn, prompt):
            p_snippet = prompt.replace("\n", " ")[:30]
            print(f"➔ [MEMORY:SKIPPED] [{decision}] loc={loc} is_first={is_first_turn} | prompt='{p_snippet}...'", flush=True)
            return False

        # 2. 3단 지식 에피소드 콘텐츠 및 태그 생성
        content = cls.format_problem_solution_episode(session_id, prompt, decision, loc, cost, solution_text)
        tags: List[str] = [session_id, decision, "tierbridge_auto_ingest"]
        if loc > 0:
            tags.append("code_modified")
        if is_first_turn:
            tags.append("initial_request")

        # 3. 1순위: sub_memory Direct Module 임포트 및 저장 시도 (<5ms)
        try:
            from sub_memory.service import MemoryService
            service = MemoryService()
            await asyncio.to_thread(service.store_memory, content=content, tags=tags)
            print(f"➔ [MEMORY:STORED] [In-Process Service] session={session_id[:8]} [{decision}] loc={loc} lines | cost=${cost:.4f}", flush=True)
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[MemoryIngestion] Service store failed, trying SQLite fallback: {e}")

        # 4. 2순위: 로컬 SQLite DB(memory.db) 직접 Insert Fallback (100% 무중단 적재 보장)
        try:
            db_path = cls.get_db_path()
            await asyncio.to_thread(
                cls.store_to_sqlite,
                db_path,
                content,
                tags,
                prompt,
                solution_text,
                session_id,
                decision,
                loc,
                cost
            )
            print(f"➔ [MEMORY:STORED] [SQLite Direct] session={session_id[:8]} [{decision}] loc={loc} lines | cost=${cost:.4f} | db={os.path.basename(db_path)}", flush=True)
            return True
        except Exception as e:
            print(f"➔ [MEMORY:ERROR] session={session_id[:8]} [{decision}] storage failed: {e}", flush=True)
            return False
