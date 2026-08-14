# 📑 Step 3: 비용/난이도 기반 기억 가중치 재강화 엔진 (Cost-Weighted Reinforcement)

이 문서는 TierBridge 하네스에서 많은 크레딧과 달러 비용(`cost_usd`)이 투입되어 해결된 고난도 대화/디버깅 턴을 감지하여, `sub-memory-bootstrap` (Giyeok) 연관 그래프(`networkx`) 및 임베딩 랭킹 상위로 Direct Module을 통해 강제 고정하는 **Step 3 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **목적**: `CHALLENGER` 등 초대규모 분석이나 막대한 크레딧을 소비하여 얻은 귀중한 트러블슈팅 지식을 일반 단순 대화 노이즈에 묻히지 않도록 그래프 연결 강도(`reinforce_memory`)를 높여 장기 보존.
- **가중치 계산 산식 (Cost-Weighted Weight Formula)**:
  $$\text{Reinforce\_Score} = \text{Base\_Score} \times \left(1.0 + \frac{\text{cost\_usd}}{0.10}\right)$$
  - 예: $0.20 달러(1 Cr) 소모 턴 ➔ 기본 가중치의 3배로 그래프 연결 강도 강화.

---

## 2. 연동 아키텍처 및 흐름

```
[Harness Turn Completed] ➔ [Extract cost_usd & decision]
                                    │
                                    ▼ [Cost Threshold Check]
                                    │ - Is cost > $0.05 or Tier == 'CHALLENGER'?
                                    ▼
                         [MemoryReinforcer.calculate_score()]
                                    │
                                    ▼
         [Direct In-process Python Import: MemoryService.reinforce_memory()]
                                    │
                                    ▼
               [Update networkx edge weight & vec rank (<5ms)]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_reinforcer.py`
```python
import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("TierBridge.MemoryReinforcer")

class MemoryReinforcer:
    COST_THRESHOLD_USD = 0.05  # $0.05 이상 소모 턴 시 강화 트리거

    @classmethod
    def compute_reinforce_weight(cls, cost_usd: float, decision: str) -> float:
        base_weight = 1.0
        if "SOL" in decision or "HIGH" in decision:
            base_weight = 2.0
        
        weight = base_weight * (1.0 + (cost_usd / 0.10))
        return round(min(weight, 10.0), 2)  # 최대 10.0 캡핑

    @classmethod
    async def trigger_reinforcement(cls, session_id: str, prompt: str, cost_usd: float, decision: str):
        if cost_usd < cls.COST_THRESHOLD_USD and "SOL" not in decision:
            return

        weight = cls.compute_reinforce_weight(cost_usd, decision)
        reason_msg = f"High value turn solved via {decision} with ${cost_usd:.4f} USD"

        try:
            from sub_memory.service import MemoryService
            service = MemoryService()
            
            # Direct In-process Reinforcement (<5ms)
            await asyncio.to_thread(
                service.reinforce_memory,
                memory_tag=session_id,
                strength_delta=weight,
                reason=reason_msg
            )
            logger.info(f"Direct Memory Reinforcement Success: [{session_id}] Weight={weight}")
        except ImportError:
            logger.warning("sub_memory module not found for reinforcement.")
        except Exception as e:
            logger.warning(f"Memory Reinforcement Direct Call Failed: {e}")
```

### 3.2 `harness.py` 연동 지점
* `harness.py`에서 `UsageTracker`로 사용량이 기록되는 시점에 `asyncio.create_task(MemoryReinforcer.trigger_reinforcement(session_id, user_prompt, cost_usd, decision))` 비동기 타격.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **가중치 산출 로직 단위 테스트**:
   * `cost_usd = 0.30` 및 `CHALLENGER` 조건 입력 시 가중치가 8.0 이상으로 정확히 계산되는지 확인.
2. **`sub-memory-bootstrap` 연관 그래프 검증**:
   * 고비용 턴 처리 후 `sub-memory-web` 대시보드(`http://127.0.0.1:8765/ui`)의 **Association Graph** 메뉴에서 대상 노드의 엣지 두께와 연결도가 높아졌는지 확인.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step3_reinforcement.md 문서를 바탕으로 Step 3 비용/난이도 기반 기억 가중치 재강화 엔진 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
