import os
import sys
import tempfile
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from tierbridge.memory_ingestion_worker import MemoryIngestionWorker
from tierbridge.usage_tracker import UsageTracker


class TestMemoryIngestionWorker(unittest.IsolatedAsyncioTestCase):

    def test_should_ingest_quality_gate(self):
        """정밀 퀄리티 게이트 및 서브스텝 노이즈 필터링 검증"""
        # 1. 서브스텝 단순 진행 보고 (LOC 0) -> 노이즈로 간주하여 제외되어야 함
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=0, is_first_turn=False, prompt="[Substep] 파일 목록을 확인했습니다."
        ))
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="SILVER", loc=0, is_first_turn=False, prompt="[Substep] [이전 대화 요약: 결제완료 화면 분석] 버튼 위치 점검 중"
        ))

        # 2. 서브스텝이지만 실제 코드를 수정한 경우 (LOC > 0) -> 지식으로 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=15, is_first_turn=False, prompt="[Substep] 버그를 수정한 코드입니다."
        ))

        # 3. 사용자의 최초 질의 (is_first_turn=True) -> 고민으로 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=0, is_first_turn=True, prompt="Lombok 호환 문제를 해결해줘."
        ))

        # 4. 비즈니스 중요 고난도 등급 (GOLD, PLATINUM, CHALLENGER) -> 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=False, prompt="복잡한 트랜잭션 분기 처리 로직 분석"
        ))
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="PLATINUM", loc=0, is_first_turn=False, prompt="분산 락 데드락 회피 아키텍처 수립"
        ))

        # 5. 초단문 또는 빈 프롬프트 -> 제외되어야 함
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=True, prompt="   "
        ))
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=True, prompt="hi"
        ))

    def test_format_problem_solution_episode(self):
        """문제-해결 3단 지식 에피소드 포맷팅 검증 (LLM 응답 솔루션 포함)"""
        episode = MemoryIngestionWorker.format_problem_solution_episode(
            session_id="019ffec0-eef3-7692-801c-60dae4e386bd",
            prompt="jCustNo 필드를 affCustNo로 변경하고 암호화 분기를 우회해줘",
            decision="GOLD",
            loc=42,
            cost=0.1523,
            solution_text="UserService.java 에서 affCustNo 필드로 매핑하고 RSA 암호화 모듈을 호출하도록 수정했습니다."
        )
        self.assertIn("[Session: 019ffec0-eef3-7692-801c-60dae4e386bd]", episode)
        self.assertIn("[Decision: GOLD]", episode)
        self.assertIn("[LOC: 42]", episode)
        self.assertIn("[Cost: $0.1523]", episode)
        self.assertIn("📌 문제 및 요구사항: jCustNo 필드를 affCustNo로 변경하고 암호화 분기를 우회해줘", episode)
        self.assertIn("💡 적용 해결책 및 LLM 응답: UserService.java 에서 affCustNo 필드로 매핑", episode)
        self.assertIn("🏷️ 태그: #GOLD #Session_019ffec0 #TierBridge", episode)

    async def test_process_log_event_with_mock_service(self):
        """MemoryService 모듈이 존재할 때 인프로세스 직접 저장 검증"""
        mock_service = MagicMock()
        mock_service.store_memory = MagicMock()

        mock_module = MagicMock()
        mock_module.MemoryService.return_value = mock_service

        with patch.dict(sys.modules, {"sub_memory.service": mock_module}):
            event = {
                "session_id": "sess_test_123",
                "prompt": "수동 심사 동기화 DTO 필드 매핑 로직 수정",
                "decision": "GOLD",
                "loc": 10,
                "cost": 0.085,
                "is_first_turn": True,
                "solution": "DTO 클래스에 @Builder 추가"
            }
            success = await MemoryIngestionWorker.process_log_event(event)
            self.assertTrue(success)
            mock_service.store_memory.assert_called_once()
            call_kwargs = mock_service.store_memory.call_args.kwargs
            self.assertIn("sess_test_123", call_kwargs["tags"])
            self.assertIn("GOLD", call_kwargs["tags"])
            self.assertIn("code_modified", call_kwargs["tags"])
            self.assertIn("initial_request", call_kwargs["tags"])
            self.assertIn("@Builder", call_kwargs["content"])

    async def test_process_log_event_sqlite_fallback(self):
        """sub_memory가 미설치된 환경에서 SQLite Direct Insert Fallback 동작 검증"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name

        try:
            with patch.dict(sys.modules, {"sub_memory.service": None}), \
                 patch.object(MemoryIngestionWorker, "get_db_path", return_value=temp_db):
                
                event = {
                    "session_id": "sess_test_sqlite_fallback",
                    "prompt": "SQLite 직결 저장 테스트 프롬프트",
                    "decision": "SILVER",
                    "loc": 5,
                    "cost": 0.02,
                    "is_first_turn": True,
                    "solution": "SQLite DB에 성공적으로 저장된 솔루션 본문"
                }
                success = await MemoryIngestionWorker.process_log_event(event)
                self.assertTrue(success)

                # SQLite DB에 실제로 INSERT 되었는지 검증
                import sqlite3
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute("SELECT content, tags FROM memories WHERE content LIKE '%sess_test_sqlite_fallback%';")
                row = cursor.fetchone()
                self.assertIsNotNone(row)
                self.assertIn("SQLite DB에 성공적으로 저장된 솔루션 본문", row[0])
                self.assertIn("tierbridge_auto_ingest", row[1])
                conn.close()
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    async def test_usage_tracker_integration(self):
        """UsageTracker.track_request 호출 시 MemoryIngestionWorker가 비동기 실행되는지 검증"""
        tracker = UsageTracker()
        
        with patch("tierbridge.memory_ingestion_worker.MemoryIngestionWorker.process_log_event") as mock_process:
            mock_process.return_value = asyncio.Future()
            mock_process.return_value.set_result(True)

            tracker.track_request(
                model="gpt-5.6-terra",
                decision="GOLD",
                input_tokens=1000,
                output_tokens=200,
                loc=25,
                session_id="sess_auto_tracker",
                prompt_text="중요 비즈니스 로직 수정 요청",
                response_text="결과 코드입니다."
            )
            # 이벤트 루프 한 틱 실행
            await asyncio.sleep(0.01)
            mock_process.assert_called_once()
            called_event = mock_process.call_args[0][0]
            self.assertEqual(called_event["session_id"], "sess_auto_tracker")
            self.assertEqual(called_event["decision"], "GOLD")
            self.assertEqual(called_event["loc"], 25)
            self.assertEqual(called_event["prompt"], "중요 비즈니스 로직 수정 요청")
            self.assertEqual(called_event["solution"], "결과 코드입니다.")
            self.assertTrue(called_event["is_first_turn"])


if __name__ == "__main__":
    unittest.main()
