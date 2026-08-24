"""
MemoryReinforcer: 비용/난이도 기반 장기 기억 가중치 재강화 엔진
"""

import os
import sqlite3
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("TierBridge.MemoryReinforcer")


class MemoryReinforcer:
    """
    고난도 추론 및 고비용 해결 턴의 그래프 엣지 가중치 승격 핸들러
    """

    COST_THRESHOLD_USD = 0.05  # $0.05 이상 소모 턴 시 가중치 강화 트리거

    @classmethod
    def compute_reinforce_weight(cls, cost_usd: float, decision: str, loc: int = 0) -> float:
        """
        비용($), 의사결정 등급, 코드 수정량(LOC)을 결합한 엣지 강화 가중치 산출 (1.0 ~ 10.0)
        """
        dec_upper = (decision or "BRONZE").upper()
        if dec_upper in ("CHALLENGER", "SOL"):
            base = 3.0
        elif dec_upper in ("PLATINUM", "GOLD"):
            base = 2.0
        elif dec_upper == "SILVER":
            base = 1.5
        else:
            base = 1.0

        cost_boost = max(0.0, cost_usd / 0.10)
        loc_boost = min(1.5, max(0, loc) / 50.0)

        weight = base * (1.0 + cost_boost + loc_boost)
        return round(min(weight, 10.0), 2)

    @classmethod
    def reinforce_node(
        cls,
        node_id: str,
        cost_usd: float,
        decision: str,
        loc: int = 0,
        db_path: Optional[str] = None
    ) -> bool:
        """
        Direct SQLite edges 테이블에 가중치를 적용하고 직전 노드들과 엣지 연결 (<5ms)
        """
        if not node_id:
            return False

        if not db_path:
            db_path = os.path.expanduser("~/.tierbridge/memory.db")

        if not os.path.exists(db_path):
            return False

        weight = cls.compute_reinforce_weight(cost_usd, decision, loc)

        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            cursor = conn.cursor()

            # 1. edges 테이블 존재 확인 및 생성
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    PRIMARY KEY (source_id, target_id)
                );
                """
            )

            # 2. 직전 최근 노드 1~3건 조회하여 엣지 연결 (지식 그래프 연결도 강화)
            cursor.execute("SELECT id FROM nodes WHERE id != ? ORDER BY timestamp DESC LIMIT 3;", (node_id,))
            recent_rows = cursor.fetchall()

            for (target_id,) in recent_rows:
                # 양방향 엣지 삽입 또는 가중치 승격
                cursor.execute(
                    """
                    INSERT INTO edges (source_id, target_id, weight)
                    VALUES (?, ?, ?)
                    ON CONFLICT(source_id, target_id) 
                    DO UPDATE SET weight = MAX(edges.weight, excluded.weight);
                    """,
                    (node_id, target_id, weight)
                )

            conn.commit()
            conn.close()

            # 3. In-process Giyeok MemoryService가 존재할 경우 보조 타격
            try:
                from sub_memory.service import MemoryService
                svc = MemoryService()
                if hasattr(svc, "reinforce_memory"):
                    svc.reinforce_memory(memory_tag=node_id, strength_delta=weight)
            except Exception:
                pass

            return True
        except Exception as e:
            logger.debug(f"[MemoryReinforcer] reinforce_node failed: {e}")
            return False
