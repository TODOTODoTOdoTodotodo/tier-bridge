# src/harnex/orchestrator/activity_tracker.py
"""
ActivityTracker: 멀티에이전트 실시간 활동(Thought, Action, Memory, Presence, Chat) 링버퍼 전담 관리자
단일 책임 원칙(SRP)에 따라 DAG별 활동 피드 저장, 직렬화, 프레즌스 상태 해석을 전담합니다.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import uuid

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import SignalMessage, SignalType, ActivityType, SubTask, TaskState


class ActivityTracker:
    """
    DAG 단위 실시간 활동 로그 및 대화형 피드를 인메모리 FIFO 링버퍼로 관리하는 전담 서비스.
    """
    def __init__(self, config: OrchestratorConfig):
        self.config = config
        self._max_history = config.event_history_limit
        # dag_id -> deque of activity dicts
        self._dag_activities: Dict[str, deque] = {}
        # subtask_id -> presence string (READY, THINKING, CODING, TESTING, COMPLETED, FAILED)
        self._subtask_presence: Dict[str, str] = {}

    def _get_buffer(self, dag_id: str) -> deque:
        if dag_id not in self._dag_activities:
            self._dag_activities[dag_id] = deque(maxlen=self._max_history)
        return self._dag_activities[dag_id]

    def _print_to_harness_log(self, item: Dict[str, Any]) -> None:
        """
        오케스트레이터의 모든 활동을 harness.log / harnex-log에 실시간 스트리밍합니다.
        """
        now_str = (item.get("timestamp") or datetime.now().isoformat()).replace("T", " ")[:19]
        dag_id = item.get("dag_id", "dag")
        sub_id = item.get("subtask_id", "ALL")
        act_type = item.get("activity_type", "LOG")
        tier = item.get("tier", "SILVER")
        msg = item.get("message", "")
        loc = item.get("loc_modified", 0)
        cr = item.get("credits_used", 0.0)

        loc_part = f" | +{loc} LOC" if loc and loc > 0 else ""
        cr_part = f" | {cr:.4f} Cr" if cr and cr > 0 else ""

        print(f"[{now_str}] [task: {dag_id}/{sub_id}] ➔ [ORCHESTRATOR: {act_type}] ({tier}) {msg}{loc_part}{cr_part}", flush=True)

    def record_signal_activity(self, dag_id: str, subtask: Optional[SubTask], signal: SignalMessage) -> Dict[str, Any]:
        """
        인입된 SignalMessage를 피드 렌더링용 활동 레코드로 변환하여 링버퍼에 저장합니다.
        """
        now_iso = signal.timestamp or datetime.now(timezone.utc).isoformat()
        act_type = signal.activity_type.value if hasattr(signal.activity_type, "value") else str(signal.activity_type)

        # SignalType 및 메시지 내용 기반 자동 activity_type 세분화 추론
        msg = signal.message or ""
        presence = "RUNNING"

        if signal.signal_type == SignalType.STARTED:
            presence = "THINKING"
            act_type = ActivityType.READY.value
        elif signal.signal_type == SignalType.COMPLETED:
            presence = "COMPLETED"
            act_type = ActivityType.ACTION.value
        elif signal.signal_type == SignalType.FAILED:
            presence = "FAILED"
            act_type = ActivityType.LOG.value
        elif signal.signal_type == SignalType.PROGRESS:
            if "thinking" in msg.lower() or "추론" in msg or "분석" in msg:
                presence = "THINKING"
                act_type = ActivityType.THOUGHT.value
            elif "test" in msg.lower() or "테스트" in msg:
                presence = "TESTING"
                act_type = ActivityType.ACTION.value
            elif signal.loc_modified > 0 or "작성" in msg or "수정" in msg or "code" in msg.lower():
                presence = "CODING"
                act_type = ActivityType.ACTION.value
            else:
                presence = "THINKING"

        if subtask:
            subtask.presence = presence
            self._subtask_presence[subtask.subtask_id] = presence

        tier = subtask.assigned_tier if subtask else "SILVER"
        subtask_title = subtask.title if subtask else signal.task_id

        activity_item = {
            "id": f"act_{uuid.uuid4().hex[:8]}",
            "dag_id": dag_id,
            "subtask_id": signal.task_id,
            "subtask_title": subtask_title,
            "tier": tier,
            "presence": presence,
            "activity_type": act_type,
            "message": msg,
            "loc_modified": signal.loc_modified,
            "credits_used": signal.credits_used,
            "worker_pid": signal.worker_pid,
            "diff_patch": signal.diff_patch,
            "injected_memory_titles": signal.injected_memory_titles,
            "timestamp": now_iso
        }

        buf = self._get_buffer(dag_id)
        buf.append(activity_item)
        self._print_to_harness_log(activity_item)
        return activity_item

    def record_memory_injection(self, dag_id: str, subtask: SubTask, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        서브태스크에 사내 장기기억이 주입되었음을 알리는 활동 기록
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        titles = [m.get("title", "") for m in memories if m.get("title")]
        msg = f"사내 기억 저장소에서 {len(memories)}건의 연관 지침을 선행 주입했습니다."
        if titles:
            msg += f" (참조: {', '.join(titles[:2])})"

        item = {
            "id": f"act_{uuid.uuid4().hex[:8]}",
            "dag_id": dag_id,
            "subtask_id": subtask.subtask_id,
            "subtask_title": subtask.title,
            "tier": subtask.assigned_tier,
            "presence": "THINKING",
            "activity_type": ActivityType.MEMORY.value,
            "message": msg,
            "loc_modified": 0,
            "credits_used": 0.0,
            "worker_pid": subtask.worker_pid,
            "diff_patch": None,
            "injected_memory_titles": titles,
            "timestamp": now_iso
        }
        buf = self._get_buffer(dag_id)
        buf.append(item)
        self._print_to_harness_log(item)
        return item

    def record_user_chat(self, dag_id: str, target_subtask_id: Optional[str], message: str) -> Dict[str, Any]:
        """
        사용자가 에이전트 관제실에서 전달한 지시(Human Intervention) 기록
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        item = {
            "id": f"act_{uuid.uuid4().hex[:8]}",
            "dag_id": dag_id,
            "subtask_id": target_subtask_id or "ALL",
            "subtask_title": "Human Operator (사용자 개입)",
            "tier": "OPERATOR",
            "presence": "INTERVENTION",
            "activity_type": ActivityType.USER_CHAT.value,
            "message": message,
            "loc_modified": 0,
            "credits_used": 0.0,
            "worker_pid": None,
            "diff_patch": None,
            "injected_memory_titles": [],
            "timestamp": now_iso
        }
        buf = self._get_buffer(dag_id)
        buf.append(item)
        self._print_to_harness_log(item)
        return item

    def record_activity(
        self,
        dag_id: str,
        subtask_id: str,
        subtask_title: str,
        tier: str,
        presence: str,
        activity_type: ActivityType,
        message: str,
        loc_modified: int = 0,
        credits_used: float = 0.0,
        worker_pid: Optional[int] = None,
        diff_patch: Optional[str] = None,
        injected_memory_titles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        임의의 활동(시스템 ACK, 중지 신호 등)을 링버퍼에 직접 기록합니다.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        act_val = activity_type.value if hasattr(activity_type, "value") else str(activity_type)
        item = {
            "id": f"act_{uuid.uuid4().hex[:8]}",
            "dag_id": dag_id,
            "subtask_id": subtask_id,
            "subtask_title": subtask_title,
            "tier": tier,
            "presence": presence,
            "activity_type": act_val,
            "message": message,
            "loc_modified": loc_modified,
            "credits_used": credits_used,
            "worker_pid": worker_pid,
            "diff_patch": diff_patch,
            "injected_memory_titles": injected_memory_titles or [],
            "timestamp": now_iso
        }
        buf = self._get_buffer(dag_id)
        buf.append(item)
        self._print_to_harness_log(item)
        return item

    def get_dag_activities(self, dag_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        특정 DAG의 최근 활동 목록 반환 (시간순 정렬)
        """
        buf = self._get_buffer(dag_id)
        items = list(buf)
        if limit and len(items) > limit:
            items = items[-limit:]
        return items

    def get_recent_global_activities(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        전체 DAG 통틀어 최근 N개 활동 반환 (대시보드 실시간 피드용)
        """
        all_acts = []
        for buf in self._dag_activities.values():
            all_acts.extend(list(buf))
        all_acts.sort(key=lambda x: x.get("timestamp", ""))
        return all_acts[-limit:] if len(all_acts) > limit else all_acts

    def get_presence(self, subtask_id: str) -> str:
        return self._subtask_presence.get(subtask_id, "READY")
