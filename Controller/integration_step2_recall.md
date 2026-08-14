# 📑 Step 2: 사전 기억 회수 (Pre-fetch Recall) & 50ms Strict 타임아웃 샌드박싱

이 문서는 Codex CLI 요청이 들어왔을 때 `sub-memory-bootstrap` (Giyeok) 저장소에서 과거 세션의 연관 지식 및 아키텍처 결정을 Direct In-process Import를 통해 5ms 이내로 회수하여 인바운드 컨텍스트에 안전하게 주입하는 **Step 2 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **하이브리드 Direct In-process 회수 (5ms Ultra-low Latency)**:
  - `sub_memory.service.MemoryService` 파이썬 모듈을 직접 임포트하여 5ms 이내로 연관 대화 기억 회수.
- **상충점 방지 (Strict 50ms Timeout & 500 Token Cap)**:
  - 인바운드 TTFT 지연 방지를 위한 **50ms Strict Timeout Sandbox** 적용.
  - 토큰 소모 인플레이션 방지를 위한 **최대 500 토큰(상위 2~3개 조각 / 1,500 자)** 캡핑.

---

## 2. 연동 아키텍처 및 흐름

```
[Inbound Request] ➔ [harness.py]
                        │
                        ▼ [MemoryPrefetcher.fetch_context()]
                        │ - Direct Python Import: MemoryService.recall_associated_memory()
                        │ - Speed: ~5ms (Timeout: 50ms strict)
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
import logging
from typing import Optional

logger = logging.getLogger("TierBridge.MemoryPrefetcher")

class MemoryPrefetcher:
    TIMEOUT_SEC = 0.050  # 50ms Strict Limit
    MAX_CHAR_LIMIT = 1500 # 약 500 토큰 캡핑

    @classmethod
    async def fetch_associated_context(cls, user_prompt: str) -> Optional[str]:
        """
        Direct In-process 5ms 이내 연관 장기 기억 회수 (Strict Sandbox)
        """
        if not user_prompt or len(user_prompt.strip()) < 5:
            return None

        try:
            from sub_memory.service import MemoryService
            service = MemoryService()
            
            # Direct In-process Memory Recall 실행 (<5ms)
            results = await asyncio.wait_for(
                asyncio.to_thread(service.recall_associated_memory, query=user_prompt[:200], limit=3),
                timeout=cls.TIMEOUT_SEC
            )
            
            if results:
                recalled_text = "\n".join([str(r) for r in results])
                return recalled_text[:cls.MAX_CHAR_LIMIT]
        except asyncio.TimeoutError:
            logger.debug("Memory Prefetch timed out (>50ms). Fallback to original prompt.")
        except ImportError:
            logger.warning("sub_memory module not imported. Skipping prefetch.")
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
   * 회수 함수에 Intentional Delay를 부여했을 때, 하네스가 정확히 50ms 만에 샌드박싱 탈출하여 원본 프롬프트로 가동되는지 검증.
2. **컨텍스트 주입 정확도 테스트**:
   * 이전 세션에서 저장된 키워드(예: "배치 타임아웃 설정값 300초") 질문 시, `MemoryPrefetcher`가 해당 지식을 회수하여 답변에 반영되는지 검증.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step2_recall.md 문서를 바탕으로 Step 2 사전 기억 회수 및 타임아웃 샌드박싱 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
