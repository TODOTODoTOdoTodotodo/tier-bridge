import os
import sys
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
        """1차 CPU 룰 기반 퀄리티 게이트 필터링 검증"""
        # 1. BRONZE 단순 스텝 (LOC 0, 첫 턴 아님) -> 제외되어야 함
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=0, is_first_turn=False, prompt="파일 목록을 확인했습니다."
        ))

        # 2. BRONZE이지만 실제 코드를 생성/수정한 경우 (LOC > 0) -> 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=15, is_first_turn=False, prompt="버그를 수정한 코드입니다."
        ))

        # 3. BRONZE이지만 세션의 최초 질의 턴인 경우 -> 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="BRONZE", loc=0, is_first_turn=True, prompt="Lombok 호환 문제를 해결해줘."
        ))

        # 4. GOLD, SILVER, PLATINUM 등 비즈니스 중요 등급 -> 수집되어야 함
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=False, prompt="복잡한 트랜잭션 분기 처리 로직 분석"
        ))
        self.assertTrue(MemoryIngestionWorker.should_ingest(
            decision="SILVER", loc=0, is_first_turn=False, prompt="API 엔드포인트 수정 사항 검토"
        ))

        # 5. 초단문 또는 빈 프롬프트 -> 제외되어야 함
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=True, prompt="   "
        ))
        self.assertFalse(MemoryIngestionWorker.should_ingest(
            decision="GOLD", loc=0, is_first_turn=True, prompt="hi"
        ))

    def test_format_problem_solution_episode(self):
        """문제-해결 3단 지식 에피소드 포맷팅 검증"""
        episode = MemoryIngestionWorker.format_problem_solution_episode(
            session_id="019ffec0-eef3-7692-801c-60dae4e386bd",
            prompt="jCustNo 필드를 affCustNo로 변경하고 암호화 분기를 우회해줘",
            decision="GOLD",
            loc=42,
            cost=0.1523
        )
        self.assertIn("[Session: 019ffec0-eef3-7692-801c-60dae4e386bd]", episode)
        self.assertIn("[Decision: GOLD]", episode)
        self.assertIn("[LOC: 42]", episode)
        self.assertIn("[Cost: $0.1523]", episode)
        self.assertIn("📌 문제 및 요구사항: jCustNo 필드를 affCustNo로 변경하고 암호화 분기를 우회해줘", episode)
        self.assertIn("💡 적용 등급 및 라우팅: GOLD", episode)
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
                "is_first_turn": True
            }
            success = await MemoryIngestionWorker.process_log_event(event)
            self.assertTrue(success)
            mock_service.store_memory.assert_called_once()
            call_kwargs = mock_service.store_memory.call_args.kwargs
            self.assertIn("sess_test_123", call_kwargs["tags"])
            self.assertIn("GOLD", call_kwargs["tags"])
            self.assertIn("code_modified", call_kwargs["tags"])
            self.assertIn("initial_request", call_kwargs["tags"])

    async def test_process_log_event_import_error_graceful_fallback(self):
        """sub_memory가 미설치된 환경에서도 오류 없이 안전하게 통과하는지 검증"""
        with patch.dict(sys.modules, {"sub_memory.service": None}):
            event = {
                "session_id": "sess_test_fallback",
                "prompt": "테스트 프롬프트 질의",
                "decision": "SILVER",
                "loc": 0,
                "cost": 0.02,
                "is_first_turn": True
            }
            # ImportError 발생 시에도 예외를 던지지 않고 False 리턴
            success = await MemoryIngestionWorker.process_log_event(event)
            self.assertFalse(success)

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
                prompt_text="중요 비즈니스 로직 수정 요청"
            )
            # 이벤트 루프 한 틱 실행
            await asyncio.sleep(0.01)
            mock_process.assert_called_once()
            called_event = mock_process.call_args[0][0]
            self.assertEqual(called_event["session_id"], "sess_auto_tracker")
            self.assertEqual(called_event["decision"], "GOLD")
            self.assertEqual(called_event["loc"], 25)
            self.assertEqual(called_event["prompt"], "중요 비즈니스 로직 수정 요청")
            self.assertTrue(called_event["is_first_turn"])


if __name__ == "__main__":
    unittest.main()
