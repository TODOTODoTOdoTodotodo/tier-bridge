# src/harnex/orchestrator/chat_manager.py
"""
ChatManager: 멀티에이전트 실시간 지시 개입(Human-in-the-Loop) 전담 관리자
단일 책임 원칙(SRP)에 따라 사용자 입력 파싱, 타깃 에이전트 라우팅, 피드 등록을 전담합니다.
"""
import re
from typing import Dict, Any, Optional

from harnex.orchestrator.activity_tracker import ActivityTracker
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.models import SignalMessage, SignalType, ActivityType


class ChatManager:
    """
    인간-에이전트 간 대화형 상호작용 및 지시 개입(Intervention) 전담 서비스.
    """
    def __init__(self, activity_tracker: ActivityTracker, signal_bus: SignalBus):
        self.activity_tracker = activity_tracker
        self.signal_bus = signal_bus
        # subtask_id -> list of pending human instructions/hints
        self._pending_hints: Dict[str, list] = {}

    def parse_target_subtask(self, text: str) -> tuple[Optional[str], str]:
        """
        메시지 내 '@subtask_id' 멘션을 파싱하여 (타깃_ID, 순수_메시지)로 분리합니다.
        예: '@sub_1 Lombok 어노테이션 유지해줘' -> ('sub_1', 'Lombok 어노테이션 유지해줘')
        """
        clean_text = text.strip()
        match = re.match(r"^@([\w\-]+)\s+(.+)$", clean_text, re.DOTALL)
        if match:
            return match.group(1), match.group(2).strip()
        return None, clean_text

    async def handle_user_message(self, dag_id: str, raw_message: str) -> Dict[str, Any]:
        """
        사용자 메시지를 처리하여 링버퍼에 등록하고 SSE 브로드캐스트를 트리거합니다.
        """
        target_subtask, clean_msg = self.parse_target_subtask(raw_message)
        activity_item = self.activity_tracker.record_user_chat(dag_id, target_subtask, clean_msg)

        if target_subtask:
            if target_subtask not in self._pending_hints:
                self._pending_hints[target_subtask] = []
            self._pending_hints[target_subtask].append(clean_msg)

        # SignalBus를 통해 실시간 SSE 가입자들에게 브로드캐스트
        signal = SignalMessage(
            task_id=target_subtask or dag_id,
            signal_type=SignalType.PROGRESS,
            activity_type=ActivityType.USER_CHAT,
            message=clean_msg
        )
        await self.signal_bus.emit_signal(signal)

        # 시스템 확인 응답(ACK) 자동 생성 및 피드 브로드캐스트
        ack_msg = f"🤖 [오케스트레이터] '{target_subtask or '전체'}' 워커에 사용자 지시가 반영되었습니다: \"{clean_msg}\""
        ack_item = self.activity_tracker.record_activity(
            dag_id=dag_id,
            subtask_id=target_subtask or "ALL",
            subtask_title="Orchestrator ACK",
            tier="SYSTEM",
            presence="READY",
            activity_type=ActivityType.ACTION,
            message=ack_msg
        )
        ack_signal = SignalMessage(
            task_id=target_subtask or dag_id,
            signal_type=SignalType.PROGRESS,
            activity_type=ActivityType.ACTION,
            message=ack_msg
        )
        await self.signal_bus.emit_signal(ack_signal)

        return {
            "status": "SENT",
            "dag_id": dag_id,
            "target_subtask_id": target_subtask,
            "message": clean_msg,
            "activity": activity_item,
            "ack": ack_item
        }

    def get_and_clear_hints_for_subtask(self, subtask_id: str) -> list[str]:
        """
        워커가 실행 전 자신에게 전달된 사용자 힌트를 수거합니다.
        """
        return self._pending_hints.pop(subtask_id, [])
