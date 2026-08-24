# 📑 Step 2: 사전 기억 회수 (Pre-fetch Recall) & 50ms Strict 타임아웃 샌드박싱

이 문서는 Codex CLI 요청이 들어왔을 때 `sub-memory-bootstrap` (Giyeok) 저장소에서 과거 세션의 연관 지식 및 아키텍처 결정을 Direct In-process Import를 통해 5ms 이내로 회수하여 인바운드 컨텍스트에 안전하게 주입하는 **Step 2 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **하이브리드 Direct In-process 회수 (5ms Ultra-low Latency)**:
  - `MemoryHandler.search_associated_memories()` 및 `sub_memory.service.MemoryService` 모듈을 직접 호출하여 5ms 이내로 연관 대화 기억 회수.
- **상충점 방지 (Strict 50ms Timeout & 500 Token Cap)**:
  - 인바운드 TTFT 지연 방지를 위한 **50ms Strict Timeout Sandbox** 적용.
  - 토큰 소모 인플레이션 방지를 위한 **최대 500 토큰(상위 1~2개 핵심 조각 / 1,000 자)** 캡핑.
  - 현재 활성 세션과 동일한 세션의 직전 턴은 자기 참조 방지를 위해 회수 대상에서 자동 제외.
- **실시간 회수/주입 하네스 로그 가시화 (Real-time Recall Logging)**:
  - 프롬프트 인입 시 기억 회수 성공 여부와 주입된 지식 내용을 `harness.log`에 실시간 명시적 출력:
    - `➔ [MEMORY:RECALLED] (Score: 95%, ID: 0fde4777) 📌 "Lombok 호환 문제..." 💡 "affCustNo 매핑..."`
    - `➔ [MEMORY:RECALL_NONE] No associated memory found for query='...'`

---

## 2. 연동 아키텍처 및 흐름

```
[Inbound User Prompt] ➔ [harness.py]
                             │
                             ▼ [MemoryPrefetcher.fetch_associated_context()]
                             │ - Speed: ~5ms (Timeout: 50ms strict sandbox)
                             │ - Token Cap: Max 500 tokens (Top 1~2 High-Score Episodes)
                             │ - Self-Session Exclude (자기 참조 방지)
                             │
              ┌──────────────┴──────────────┐
              ▼ (Within 50ms & Match >= 75%) ▼ (No Match / Timeout > 50ms)
        [Memory Context Found]         [Pass Original Prompt]
              │                              │
              ▼                              ▼
    [Log: MEMORY:RECALLED]         [Log: MEMORY:RECALL_NONE]
              │                              │
    [Inject Context Block]                   │
              │                              │
              └──────────────┬───────────────┘
                             ▼
                 [Forward to LLM Backend]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_prefetcher.py`
```python
import asyncio
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("TierBridge.MemoryPrefetcher")

class MemoryPrefetcher:
    TIMEOUT_SEC = 0.050    # 50ms Strict Limit
    MAX_CHAR_LIMIT = 1000  # 약 300~500 토큰 캡핑

    @classmethod
    async def fetch_associated_context(cls, user_prompt: str, current_session_id: str = "") -> Optional[str]:
        """
        50ms Strict Sandbox 내에서 연관 장기 기억 회수 및 실시간 로그 방출
        """
        if not user_prompt or len(user_prompt.strip()) < 5:
            return None

        # 서브스텝 단순 진행 보고는 회수 트리거 제외
        if user_prompt.strip().startswith("[Substep]"):
            return None

        try:
            from tierbridge.memory_handler import MemoryHandler
            
            # 50ms Strict 타임아웃 샌드박싱
            results = await asyncio.wait_for(
                asyncio.to_thread(MemoryHandler.search_associated_memories, query=user_prompt[:200], limit=2),
                timeout=cls.TIMEOUT_SEC
            )
            
            # 현재 세션 자기 참조 배제 및 유효성 검사
            valid_memories = [
                r for r in (results or [])
                if r.get("session_id") != current_session_id and r.get("score", 0.0) >= 0.75
            ]

            if valid_memories:
                top_m = valid_memories[0]
                prob_snippet = (top_m.get("problem") or "")[:35].replace("\n", " ")
                sol_snippet = (top_m.get("solution") or "")[:35].replace("\n", " ")
                score_pct = int(top_m.get("score", 0.95) * 100)
                m_id = str(top_m.get("id", ""))[:8]
                
                # 실시간 하네스 로그 방출
                print(f"➔ [MEMORY:RECALLED] (Score: {score_pct}%, ID: {m_id}) 📌 '{prob_snippet}...' 💡 '{sol_snippet}...'", flush=True)

                injected_lines = ["[🧠 Giyeok 장기 기억저장소 참조 지식]"]
                for m in valid_memories[:2]:
                    injected_lines.append(f"- 과거 문제: {m.get('problem')}")
                    injected_lines.append(f"- 해결 방안: {m.get('solution')}")
                
                recalled_text = "\n".join(injected_lines)
                return recalled_text[:cls.MAX_CHAR_LIMIT]
            else:
                print(f"➔ [MEMORY:RECALL_NONE] No associated memory found | query='{user_prompt[:30]}...'", flush=True)
        except asyncio.TimeoutError:
            print("➔ [MEMORY:RECALL_TIMEOUT] Memory Prefetch timed out (>50ms). Fallback to original prompt.", flush=True)
        except Exception as e:
            logger.debug(f"Memory Prefetch skipped: {e}")

        return None
```

### 3.2 `harness.py` 연동 지점
* `harness.py`에서 `unified_req` 수신 직후:
  ```python
  recalled_context = await MemoryPrefetcher.fetch_associated_context(user_prompt, current_session_id=session_id)
  if recalled_context:
      # unified_req 메시지 상단에 참조 시스템 컨텍스트로 결합 주입
      unified_req.messages.insert(0, Message(role="system", content=recalled_context))
  ```

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **타임아웃 샌드박싱 테스트**:
   * 회수 함수에 Intentional Delay를 부여했을 때, 하네스가 정확히 50ms 만에 샌드박싱 탈출하여 원본 프롬프트로 가동되는지 검증.
2. **컨텍스트 주입 정확도 테스트**:
   * 이전 세션에서 저장된 키워드(예: "배치 타임아웃 설정값 300초") 질문 시, `MemoryPrefetcher`가 해당 지식을 회수하여 답변에 반영되는지 검증.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step2_recall.md 문서를 바탕으로 Step 2 사전 기억 회수 및 타임아웃 샌드박싱 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
