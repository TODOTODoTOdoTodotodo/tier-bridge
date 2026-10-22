# src/harnex/orchestrator/chat_manager.py
"""
ChatManager: 멀티에이전트 실시간 지시 개입(Human-in-the-Loop) 전담 관리자
단일 책임 원칙(SRP)에 따라 사용자 입력 파싱, 타깃 에이전트 라우팅, 피드 등록을 전담합니다.
"""
import re
from typing import Dict, Any, Optional

from harnex.orchestrator.activity_tracker import ActivityTracker
from harnex.orchestrator.signal_bus import SignalBus
from harnex.orchestrator.models import SignalMessage, SignalType, ActivityType, TaskState


class ChatManager:
    """
    인간-에이전트 간 대화형 상호작용 및 지시 개입(Intervention) 전담 서비스.
    """
    def __init__(self, activity_tracker: ActivityTracker, signal_bus: SignalBus, dag_registry: Optional[Dict[str, Any]] = None):
        self.activity_tracker = activity_tracker
        self.signal_bus = signal_bus
        self.dag_registry = dag_registry if dag_registry is not None else {}
        # subtask_id -> list of pending human instructions/hints
        self._pending_hints: Dict[str, list] = {}

    def is_status_query(self, message: str) -> bool:
        """
        사용자 입력이 에이전트/워커 상태 질의인지 판별합니다.
        """
        keywords = ["상태", "뭐해", "뭐하고", "뭐하냐", "보고", "진행", "어디까지", "status", "ping", "alive"]
        clean = message.strip().lower()
        return any(kw in clean for kw in keywords)

    def _get_active_dag(self, dag_id: str) -> Optional[Any]:
        """
        지정된 dag_id 또는 현재 실행 중인 활성 TaskDAG를 반환합니다.
        """
        if dag_id in self.dag_registry:
            dag = self.dag_registry[dag_id]
            state_val = dag.state.value if hasattr(dag.state, "value") else str(dag.state)
            if state_val in ("RUNNING", TaskState.RUNNING.value):
                return dag
        for d in self.dag_registry.values():
            state_val = d.state.value if hasattr(d.state, "value") else str(d.state)
            if state_val in ("RUNNING", TaskState.RUNNING.value):
                return d
        return None

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

        active_dag = self._get_active_dag(dag_id)
        is_query = self.is_status_query(clean_msg)

        if is_query:
            if not active_dag:
                ack_msg = "ℹ️ [오케스트레이터] 현재 실행 중인 에이전트 작업(Task)이 없습니다. (모든 에이전트 유휴 상태) 새로운 작업을 시작하시려면 목표를 자연어로 입력해 주세요."
            elif target_subtask:
                if target_subtask in active_dag.subtasks:
                    sub = active_dag.subtasks[target_subtask]
                    presence_val = sub.presence or "READY"
                    state_val = sub.state.value if hasattr(sub.state, "value") else str(sub.state)
                    loc_val = sub.loc_modified or 0
                    cr_val = sub.credits_used or 0.0
                    ack_msg = f"🤖 [{target_subtask} 상태 보고] 현재 상태: {presence_val} ({state_val}) | 할당 모델: {sub.assigned_tier} | 작업: {sub.title} | 수정: +{loc_val} LOC | 소모: {cr_val:.4f} Cr"
                else:
                    valid_subs = ", ".join(active_dag.subtasks.keys())
                    ack_msg = f"⚠️ [오케스트레이터] 현재 작업('{active_dag.title}')에 '{target_subtask}' 워커가 없습니다. (현재 워커 목록: {valid_subs})"
            else:
                summary_lines = []
                for sid, s in active_dag.subtasks.items():
                    presence_val = s.presence or "READY"
                    summary_lines.append(f"• {sid} ({s.assigned_tier}): {presence_val} - {s.title}")
                summary_str = " | ".join(summary_lines)
                ack_msg = f"🤖 [전체 에이전트 상태 보고] 활성 작업: '{active_dag.title}' | {summary_str}"
        elif not active_dag:
            if target_subtask:
                if target_subtask not in self._pending_hints:
                    self._pending_hints[target_subtask] = []
                self._pending_hints[target_subtask].append(clean_msg)
                ack_msg = f"🤖 [오케스트레이터] '{target_subtask}' 워커에 사용자 지시가 반영되었습니다: \"{clean_msg}\""
            else:
                ack_msg = f"⚠️ [오케스트레이터] 지시를 전달할 활성 워커가 없습니다 (현재 모든 에이전트 유휴 상태). 먼저 신규 작업을 발주해 주세요: \"{clean_msg}\""
        else:
            if target_subtask:
                if target_subtask not in self._pending_hints:
                    self._pending_hints[target_subtask] = []
                self._pending_hints[target_subtask].append(clean_msg)
            ack_msg = f"🤖 [오케스트레이터] '{target_subtask or '전체'}' 워커에 사용자 지시가 반영되었습니다: \"{clean_msg}\""

        # SignalBus를 통해 실시간 SSE 가입자들에게 브로드캐스트
        signal = SignalMessage(
            task_id=target_subtask or dag_id,
            signal_type=SignalType.PROGRESS,
            activity_type=ActivityType.USER_CHAT,
            activity_id=activity_item.get("id"),
            message=clean_msg,
            skip_activity_tracking=True
        )
        await self.signal_bus.emit_signal(signal)

        # 시스템 확인 응답(ACK) 자동 생성 및 피드 브로드캐스트
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
            activity_id=ack_item.get("id"),
            message=ack_msg,
            skip_activity_tracking=True
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
