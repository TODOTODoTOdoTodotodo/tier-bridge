# 📑 Step 2: 사전 기억 회수 (Pre-fetch Recall) & 50ms Strict 타임아웃 샌드박싱

이 문서는 Codex CLI 요청이 들어왔을 때 `sub-memory-bootstrap` (Giyeok) 저장소에서 과거 세션의 연관 지식 및 아키텍처 결정을 50ms 이내로 회수하여 인바운드 컨텍스트에 안전하게 주입하는 **Step 2 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **목적**: 새로운 세션이나 대화 턴에서도 과거 세션(`sess_xxx`)에서 해결했던 아키텍처 결정 및 트러블슈팅 지식을 `recall_associated_memory`로 가져와 에이전트 프롬프트에 자동 반영.
- **상충점 방지 (Strict 50ms Timeout & 500 Token Cap)**:
  - 벡터 검색 지연으로 인한 TTFT 저하를 막기 위해 **50ms Strict Timeout** 적용 (50ms 초과 시 즉시 원본 프롬프트로 진행).
  - 과거 기억 대량 삽입으로 인한 토큰 소모 증가를 막기 위해 **최대 500 토큰(상위 2~3개 조각)**으로 캡핑.

---

## 2. 연동 아키텍처 및 흐름

```
[Inbound Request] ➔ [harness.py]
                        │
                        ▼ [MemoryPrefetcher.fetch_context()]
                        │ - Timeout: 50ms strict
                        │ - Token Cap: Max 500 tokens
                        │
         ┌──────────────┴──────────────┐
         ▼ (Within 50ms)               ▼ (Timeout or Failed)
   [Memory Context Retrieved]    [Pass Original Prompt]
         │                             │
         └──────────────┬──────────────┘
                        ▼
            [Forward to LLM Backend]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_prefetcher.py`
```python
import asyncio
import httpx
import logging
from typing import Optional

logger = logging.getLogger("TierBridge.MemoryPrefetcher")

class MemoryPrefetcher:
    MCP_ENDPOINT = "http://127.0.0.1:8766/mcp"
    TIMEOUT_SEC = 0.050  # 50ms Strict Limit
    MAX_CHAR_LIMIT = 1500 # 약 500 토큰 캡핑

    @classmethod
    async def fetch_associated_context(cls, user_prompt: str) -> Optional[str]:
        """
        50ms 이내 연관 장기 기억 회수 (Strict Sandbox)
        """
        if not user_prompt or len(user_prompt.strip()) < 5:
            return None

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "recall_associated_memory",
                "arguments": {
                    "query": user_prompt[:200],
                    "limit": 3
                }
            },
            "id": 1
        }

        try:
            async with httpx.AsyncClient(timeout=cls.TIMEOUT_SEC) as client:
                res = await client.post(cls.MCP_ENDPOINT, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    result_text = str(data.get("result", {}))
                    if result_text and "result" in data:
                        return result_text[:cls.MAX_CHAR_LIMIT]
        except asyncio.TimeoutError:
            logger.debug("Memory Prefetch timed out (>50ms). Fallback to original prompt.")
        except Exception as e:
            logger.debug(f"Memory Prefetch skipped: {e}")

        return None
```

### 3.2 `harness.py` 연동 지점
* `harness.py`에서 `unified_req` 수신 직후 `recalled_context = await MemoryPrefetcher.fetch_associated_context(user_prompt)` 호출.
* `recalled_context`가 존재할 경우, `unified_req.messages` 상단에 `[Retrieved Long-term Memory Context]` 시스템 블록으로 안전하게 병합.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **타임아웃 샌드박싱 테스트**:
   * MCP 서버 응답에 Intentional Delay를 부여했을 때, 하네스가 정확히 50ms 만에 샌드박싱 탈출하여 원본 프롬프트로 처리되는지 검증.
2. **컨텍스트 주입 정확도 테스트**:
   * 이전 세션에서 저장된 키워드(예: "배치 타임아웃 설정값 300초") 질문 시, `MemoryPrefetcher`가 해당 지식을 회수하여 답변에 반영되는지 검증.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step2_recall.md 문서를 바탕으로 Step 2 사전 기억 회수 및 타임아웃 샌드박싱 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
