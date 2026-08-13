# 📑 Step 1: 비동기 세션 로그 수집 파이프라인 & 퀄리티 게이팅 (Ingestion Worker)

이 문서는 TierBridge 하네스에서 수집된 세션 로그(`session_id`, `prompt`, `decision`, `cost` 등)를 `sub-memory-bootstrap` (Giyeok) 장기 기억 저장소로 무중단 비동기 수집하기 위한 **Step 1 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **목적**: TierBridge 하네스의 응답 속도(TTFT)에 0ms 영향을 주지 않으면서, 대화 턴 완료 직후 중요 대화 문맥을 `sub-memory-bootstrap` (`http://127.0.0.1:8766/mcp` 또는 REST)으로 비동기 수집.
- **노이즈 방지 (Selective Ingestion Gating)**: 단순 파일 조회나 단문 스크립트 실행 스텝(`LUNA:LOW`)은 수집에서 제외하고, 의미 있는 비즈니스 턴(`LUNA:MEDIUM` 이상 또는 사용자 턴 1)만 선별 수집.

---

## 2. 연동 아키텍처 및 흐름

```
[harness.py Request End]
          │
          ├───► Client Response Delivery (TTFT 0ms Delay)
          │
          └───► asyncio.create_task(IngestionWorker.enqueue(...))
                      │
                      ▼ [Quality Gate Filter]
                      │ - Check decision != 'LUNA:LOW' or is_user_turn_1
                      ▼
               [HTTP POST /mcp - store_memory] ➔ [sub-memory memory.db]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_ingestion_worker.py`
```python
import asyncio
import httpx
import logging
from typing import Dict, Any

logger = logging.getLogger("TierBridge.MemoryIngestion")

class MemoryIngestionWorker:
    MCP_ENDPOINT = "http://127.0.0.1:8766/mcp"
    
    @classmethod
    async def process_log_event(cls, event: Dict[str, Any]):
        """
        Quality Gating & Async Memory Store Target
        """
        decision = event.get("decision", "")
        # LUNA:LOW 단순 스텝은 저장 제외 (노이즈 방지)
        if decision == "LUNA:LOW" and not event.get("is_first_turn", False):
            return

        session_id = event.get("session_id", "sess_default")
        prompt = event.get("prompt", "")
        cost = event.get("cost", 0.0)

        if not prompt:
            return

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "store_memory",
                "arguments": {
                    "content": f"[Session: {session_id}] [Cost: ${cost:.4f}] {prompt}",
                    "tags": [session_id, decision, "tierbridge_auto_ingest"]
                }
            },
            "id": 1
        }

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(cls.MCP_ENDPOINT, json=payload)
        except Exception as e:
            logger.warning(f"Memory Ingestion Async Post Failed (non-blocking): {e}")
```

### 3.2 `harness.py` 이벤트 연동 지점
* `harness.py` 내 `route_harness` 함수의 StreamingResponse 리턴 직전 또는 트래커 호출 시점에 `asyncio.create_task(MemoryIngestionWorker.process_log_event(event_data))` 호출.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **독립 모듈 테스트**:
   ```bash
   python -c "import asyncio; from src.tierbridge.memory_ingestion_worker import MemoryIngestionWorker; asyncio.run(MemoryIngestionWorker.process_log_event({'session_id': 'sess_test1', 'prompt': '테스트 지식 저장', 'decision': 'TERRA:MEDIUM', 'cost': 0.12}))"
   ```
2. **하네스 실시간 연동 테스트**:
   * `run_harness.sh` 가동 후 Codex CLI로 프롬프트 전송.
   * `sub-memory-bootstrap` MCP 로그 또는 대시보드(`http://127.0.0.1:8765/ui`)에서 `sess_...` 태그와 함께 `store_memory` 노드가 자동 생성되었는지 확인.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step1_ingestion.md 문서를 바탕으로 Step 1 비동기 세션 로그 수집 파이프라인 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
