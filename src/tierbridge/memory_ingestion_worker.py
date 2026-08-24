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
        SQLite memory.db 테이블 직접 Insert (submemory 표준 규격: 순수 User/Assistant 지식 쌍 보존)
        """
        clean_sol = (solution_text or content).strip()
        if not clean_sol or clean_sol in ("(답변 수집 완료)", f"라우팅 등급: {decision}"):
            return False

        conn = sqlite3.connect(db_path, timeout=5.0)
        cursor = conn.cursor()

        # 1. Giyeok nodes 테이블 지원 (순수 User / Assistant 텍스트만 보존)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
        has_nodes = cursor.fetchone() is not None

        if has_nodes:
            clean_p = prompt.strip()
            # 동일 질문의 이전 중간 턴이 있다면 삭제 후 최종 1:1 쌍으로 대체 (Single Pair Guarantee)
            cursor.execute("DELETE FROM nodes WHERE text LIKE ?;", (f"User: {clean_p}\n%",))

            node_id = str(uuid.uuid4())
            node_text = f"User: {clean_p}\nAssistant: {clean_sol}"
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
        clean_p = prompt.strip()
        cursor.execute("DELETE FROM memories WHERE content LIKE ?;", (f"User: {clean_p}\n%",))
        cursor.execute("INSERT INTO memories (content, tags) VALUES (?, ?);", (f"User: {clean_p}\nAssistant: {clean_sol}", tags_json))

        conn.commit()
        conn.close()
        return True

    @classmethod
    def is_tool_call_payload(cls, text: str) -> bool:
        """
        응답 텍스트가 내부 쉘/도구 실행용 JSON 페이로드인지 판별 (최종 답변 선별용)
        """
        if not text:
            return False
        t = text.strip()
        if t.startswith('{"cmd":') or t.startswith('{"name":') or t.startswith('{"tool":') or t.startswith('{"function":') or t.startswith('{"action":'):
            return True
        if t.startswith('{"call":') or t.startswith('{"tool_call_id":'):
            return True
        try:
            obj = json.loads(t)
            if isinstance(obj, dict) and any(k in obj for k in ("cmd", "command", "tool_calls", "function_call", "action", "yield_time_ms")):
                return True
        except Exception:
            pass
        return False

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
        사용자의 고민과 LLM의 최종 해결책/코드를 순수 질문-답변 지식 포맷으로 표준화
        """
        clean_prompt = prompt.strip()
        clean_sol = solution_text.strip()
        return f"User: {clean_prompt}\nAssistant: {clean_sol}"

    @classmethod
    def should_ingest(cls, decision: str, loc: int, is_first_turn: bool, prompt: str) -> bool:
        """
        CPU 룰 기반 기본 퀄리티 게이트 ($0.00)
        - 빈 프롬프트 또는 5자 미만 초단문 배제
        - [Substep]으로 시작하는 순수 내부 독백 턴만 배제 (코드 수정 턴 제외)
        """
        if not prompt or len(prompt.strip()) < 5:
            return False

        p_clean = prompt.strip()
        # [Substep]으로 시작하는 순수 내부 독백 턴만 배제
        if p_clean.startswith("[Substep]") and loc == 0:
            return False

        return True

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
            print(f"➔ [MEMORY:SKIPPED] [{decision}] loc={loc} | prompt='{p_snippet}...' (quality gate)", flush=True)
            return False

        # 2. 답변 내용 유효성 검증 (답변이 비어있는 껍데기 턴은 저장 배제)
        if not solution_text or len(solution_text.strip()) < 5:
            p_snippet = prompt.replace("\n", " ")[:30]
            print(f"➔ [MEMORY:SKIPPED] [{decision}] | prompt='{p_snippet}...' (no solution text)", flush=True)
            return False

        # 3. 도구 호출 턴 배제 (프로토콜 레벨 최종 완료 답변 플래그 is_final_answer 검증)
        is_final_answer = event.get("is_final_answer", True)
        if not is_final_answer or cls.is_tool_call_payload(solution_text):
            p_snippet = prompt.replace("\n", " ")[:30]
            print(f"➔ [MEMORY:SKIPPED] [{decision}] | prompt='{p_snippet}...' (tool turn / not final answer)", flush=True)
            return False

        # 3. 순수 질문-답변 지식 에피소드 생성
        content = cls.format_problem_solution_episode(session_id, prompt, decision, loc, cost, solution_text)
        tags: List[str] = [session_id, decision, "tierbridge_auto_ingest"]
        if loc > 0:
            tags.append("code_modified")
        if is_first_turn:
            tags.append("initial_request")

        # 4. 1순위: sub_memory Direct Module 임포트 및 저장 시도 (<5ms)
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

        # 5. 2순위: 로컬 SQLite DB(memory.db) 직접 Insert Fallback (100% 무중단 적재 보장)
        try:
            db_path = cls.get_db_path()
            success = await asyncio.to_thread(
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
            if success:
                print(f"➔ [MEMORY:STORED] [SQLite Direct] session={session_id[:8]} [{decision}] loc={loc} lines | cost=${cost:.4f} | db={os.path.basename(db_path)}", flush=True)
                return True
            else:
                return False
        except Exception as e:
            print(f"➔ [MEMORY:ERROR] session={session_id[:8]} [{decision}] storage failed: {e}", flush=True)
            return False
