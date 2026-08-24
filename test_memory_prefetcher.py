"""
Unit tests for MemoryPrefetcher (Step 2 Pre-fetch Recall & 50ms Strict Sandbox)
"""

import os
import sys
import time
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from tierbridge.memory_prefetcher import MemoryPrefetcher
from tierbridge.memory_handler import MemoryHandler
from tierbridge.models import UnifiedRequest, Message


class TestMemoryPrefetcher(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_memory = {
            "id": "node_test_12345678",
            "session_id": "sess_past_other_user",
            "problem": "Lombok @Getter 호환성 오류 해결 및 DTO 리팩토링",
            "solution": "UserService.java에서 @Builder 대신 @RequiredArgsConstructor를 적용하고 DTO를 분리했습니다.",
            "decision": "GOLD",
            "loc": 45,
            "score": 0.95,
            "created_at": "2026-08-20T10:00:00Z"
        }

    async def test_prefetch_successful_recall(self):
        """유사 기억이 존재할 때 50ms 이내 정상 회수 및 Soft Reference 주입 블록 생성 검증"""
        with patch.object(MemoryHandler, "search_associated_memories", return_value=[self.mock_memory]):
            result = await MemoryPrefetcher.fetch_associated_context(
                user_prompt="Lombok DTO 리팩토링 중 오류가 발생했어",
                current_session_id="sess_current_active"
            )
            self.assertIsNotNone(result)
            self.assertIn("[🧠 Giyeok 장기 기억저장소 참고 지식]", result)
            self.assertIn("Lombok @Getter 호환성 오류", result)
            self.assertIn("UserService.java에서 @Builder 대신", result)
            self.assertIn("적합도: 95%", result)

    async def test_prefetch_substep_skipping(self):
        """[Substep] 접두사 진행 보고는 회수 트리거에서 제외되는지 검증"""
        with patch.object(MemoryHandler, "search_associated_memories") as mock_search:
            result = await MemoryPrefetcher.fetch_associated_context(
                user_prompt="[Substep] 파일 목록을 확인하고 핵심 책임을 요약할게요.",
                current_session_id="sess_current"
            )
            self.assertIsNone(result)
            mock_search.assert_not_called()

    async def test_prefetch_short_prompt_skipping(self):
        """5자 미만 초단문/공백은 회수에서 제외되는지 검증"""
        with patch.object(MemoryHandler, "search_associated_memories") as mock_search:
            result = await MemoryPrefetcher.fetch_associated_context(
                user_prompt="hi",
                current_session_id="sess_current"
            )
            self.assertIsNone(result)
            mock_search.assert_not_called()

    async def test_prefetch_self_session_exclusion(self):
        """현재 활성 세션과 동일한 세션의 직전 턴은 자기 참조 방지를 위해 제외되는지 검증"""
        same_session_memory = dict(self.mock_memory)
        same_session_memory["session_id"] = "sess_current_active"

        with patch.object(MemoryHandler, "search_associated_memories", return_value=[same_session_memory]):
            result = await MemoryPrefetcher.fetch_associated_context(
                user_prompt="Lombok 호환성 문제 해결",
                current_session_id="sess_current_active"
            )
            self.assertIsNone(result)

    async def test_prefetch_timeout_strict_sandbox(self):
        """검색이 50ms를 초과할 경우 샌드박스가 즉시 탈출하여 None을 반환하는지 검증"""
        def slow_search(query, limit):
            time.sleep(0.080)  # 80ms 지연 (50ms 한도 초과)
            return [self.mock_memory]

        with patch.object(MemoryHandler, "search_associated_memories", side_effect=slow_search):
            start_t = time.time()
            result = await MemoryPrefetcher.fetch_associated_context(
                user_prompt="Lombok 빌드 오류 점검",
                current_session_id="sess_current_active"
            )
            elapsed = time.time() - start_t
            self.assertIsNone(result)
            # 타임아웃 50ms + 스케줄링 오버헤드 감안 150ms 이내에 안전 탈출
            self.assertLess(elapsed, 0.150)

    def test_format_soft_reference_block_char_cap(self):
        """주입 텍스트가 MAX_CHAR_LIMIT(1000자) 이내로 캡핑되는지 검증"""
        long_mem = dict(self.mock_memory)
        long_mem["solution"] = "A" * 2000
        block = MemoryPrefetcher.format_soft_reference_block([long_mem])
        self.assertLessEqual(len(block), 1050)
        self.assertIn("... (이하 생략)", block)


if __name__ == "__main__":
    unittest.main()
