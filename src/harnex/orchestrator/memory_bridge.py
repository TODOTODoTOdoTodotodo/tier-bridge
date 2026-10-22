# src/harnex/orchestrator/memory_bridge.py
"""
TaskMemoryBridge: SubTask 장기 기억(GiyEOK) 선행 검색 및 주입 전담 브리지
단일 책임 원칙(SRP)에 따라 서브태스크 지시문과 연관된 사내 기억을 선행 탐색(Pre-fetch)하고
에이전트 컨텍스트에 주입할 요약본을 생성하는 책임을 전담합니다.
"""
import logging
from typing import Dict, Any, List, Optional

from harnex.orchestrator.config import OrchestratorConfig
from harnex.orchestrator.models import SubTask

logger = logging.getLogger("Harnex.TaskMemoryBridge")


class TaskMemoryBridge:
    """
    SubTask 지시문과 연관된 사내 장기기억을 탐색하여 주입하는 전담 서비스.
    """
    def __init__(self, config: OrchestratorConfig):
        self.config = config

    def prefetch_memories_for_subtask(self, subtask: SubTask) -> List[Dict[str, Any]]:
        """
        SubTask의 instruction 및 title을 기반으로 GiyEOK에서 연관 사내 지식을 탐색합니다.
        반환 형태: List of { "id": str, "title": str, "summary": str, "score": float }
        """
        if not self.config.memory_injection_enabled:
            return []

        query = f"{subtask.title} {subtask.instruction}".strip()
        if not query:
            return []

        try:
            try:
                from harnex.memory_handler import MemoryHandler
            except ImportError:
                from src.harnex.memory_handler import MemoryHandler

            top_k = self.config.memory_injection_top_k
            results = MemoryHandler.search_associated_memories(query, limit=top_k)
            injected = []
            for r in results:
                title = r.get("problem") or r.get("id") or "사내 컨벤션/이슈"
                if len(title) > 60:
                    title = title[:57] + "..."
                summary = r.get("solution") or r.get("raw_content") or ""
                if len(summary) > 120:
                    summary = summary[:117] + "..."
                injected.append({
                    "id": str(r.get("id", "mem_node")),
                    "title": title,
                    "summary": summary,
                    "score": round(float(r.get("score", 0.85)), 2)
                })
            return injected
        except Exception as e:
            logger.debug(f"Memory pre-fetch failed for subtask {subtask.subtask_id}: {e}")
            return []

    def format_memory_injection_prompt(self, memories: List[Dict[str, Any]]) -> str:
        """
        워커 에이전트 프롬프트에 선행 주입할 시스템 컨텍스트 블록 생성
        """
        if not memories:
            return ""

        lines = ["[사내 장기기억(GiyEOK) 선행 주입 지침]"]
        for m in memories:
            lines.append(f"• 📌 {m['title']} (유사도 {int(m.get('score', 0.85) * 100)}%)")
            if m.get("summary"):
                lines.append(f"  ↳ 핵심 해결책: {m['summary']}")
        return "\n".join(lines)
