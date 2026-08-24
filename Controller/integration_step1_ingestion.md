# 📑 Step 1: 비동기 세션 로그 수집 파이프라인 & 퀄리티 게이팅 (Ingestion Worker)

이 문서는 TierBridge 하네스에서 수집된 세션 로그(`session_id`, `prompt`, `decision`, `cost`, `loc` 등)를 `sub-memory-bootstrap` (Giyeok) 장기 기억 저장소로 무중단 초고속 수집하고, **"고민(Problem) ➔ 해결(Solution) ➔ 결과(Outcome)"의 고품질 지식 에피소드**로 구조화하여 적재하기 위한 **Step 1 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **TierBridge 단일 통합 레포 및 런타임 일원화 (Unified Storage Policy)**:
  - 분리된 외부 레포/경로(`~/.codex/sub-memory/`) 대신, TierBridge 런타임 홈 **`~/.tierbridge/memory.db`** 로 장기 기억 저장소 DB를 일원화하여 단일 패키지로 관리.
  - 기존 `~/.codex/sub-memory/memory.db`의 지식 데이터는 `~/.tierbridge/memory.db`로 자동 무손실 마이그레이션.
- **하이브리드 아키텍처 (Hybrid Dual Architecture)**:
  1. **하네스 비동기 수집 (Direct Module In-process 5ms)**: 하네스 내부에서는 MCP HTTP 오버헤드 없이 파이썬 모듈 및 SQLite 직결로 5ms 이내 비동기 인메모리/DB 직접 수집.
  2. **MCP 인터페이스 유지**: 에이전트 자율 툴 호출 및 `sub-memory-web` UI 연동을 위해 MCP Protocol(Port 8766)도 듀얼 노출.
- **비용 절감 & 초저비용 지식 증류 (Zero-Cost / Low-Cost Distillation)**:
  1. **CPU 룰 기반 1차 컷 ($0.00)**: 단순 조회/오타/단문 스크립트(`BRONZE`, `LOC=0`)는 CPU 레벨에서 0원으로 사전 탈락.
  2. **LUNA 경량 모델 3단 정제 (건당 ~$0.0001 / 0.0005 Cr)**: 선별된 20%의 핵심 에피소드만 `[문제]-[해결책]-[메타태그]` 3단 구조로 정제하여 벡터화.
- **문제-해결 에피소드 번들링 (Problem-Solution Episode Bundling)**:
  - 단편적인 턴 수집의 한계를 극복하고, 사용자의 최초 고민과 최종 코드 해결 결과를 1개의 에피소드 단위로 결합 보존.

---

## 2. 연동 아키텍처 및 흐름

```
[harness.py Request End]
          │
          ├───► 🚀 Client Response Delivery (TTFT 0ms Delay)
          │
          └───► ⚙️ asyncio.create_task(MemoryIngestionWorker.process_log_event(...))
                      │
                      ▼ 🛡️ [1차 컷: CPU 룰 기반 필터 (비용 $0.00)]
                      │   - decision != 'BRONZE' or is_first_turn or loc > 0
                      ▼
                      🧠 [2차 정제: LUNA 경량 모델 3단 증류 (선택적 / 턴당 $0.0001)]
                      │   - 3단 포맷: [문제(Problem)] - [해결(Solution)] - [태그(Tags)]
                      ▼
               [Direct In-process Python Import: MemoryService.store_memory()]
                      │
                      ▼
             [SQLite ~/.tierbridge/memory.db Direct Update (<5ms, 비용 $0.00)]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_ingestion_worker.py`
```python
import asyncio
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("TierBridge.MemoryIngestion")

class MemoryIngestionWorker:
    @classmethod
    def format_problem_solution_episode(
        cls,
        session_id: str,
        prompt: str,
        decision: str,
        loc: int,
        cost: float,
        solution_text: str = ""
    ) -> str:
        """
        문제-해결 3단 지식 표준 포맷 생성 (사용자 고민 + LLM 최종 해결책/코드 + 메타태그)
        """
        clean_prompt = prompt.strip()
        clean_sol = solution_text.strip() if solution_text else f"라우팅 등급: {decision}"
        if len(clean_sol) > 1000:
            clean_sol = clean_sol[:1000] + "... (이하 생략)"

        return (
            f"[Session: {session_id}] [Decision: {decision}] [LOC: {loc}] [Cost: ${cost:.4f}]\n"
            f"- 📌 문제 및 요구사항: {clean_prompt}\n"
            f"- 💡 적용 해결책 및 LLM 응답: {clean_sol}\n"
            f"- 🏷️ 태그: #{decision} #Session_{session_id[:8]} #TierBridge"
        )

    @classmethod
    async def process_log_event(cls, event: Dict[str, Any]) -> bool:
        """
        Direct Module In-process Store + SQLite Direct Insert Fallback + 실시간 로깅
        """
        decision = event.get("decision", "UNKNOWN")
        loc = event.get("loc", 0)
        is_first_turn = event.get("is_first_turn", False)
        prompt = event.get("prompt", "")
        session_id = event.get("session_id", "sess_default")
        cost = event.get("cost", 0.0)
        solution_text = event.get("solution", "")

        # 1차 CPU 룰 기반 노이즈 컷 ($0.00): 5자 미만 초단문만 배제
        if not cls.should_ingest(decision, loc, is_first_turn, prompt):
            print(f"➔ [MEMORY:SKIPPED] [{decision}] loc={loc} is_first={is_first_turn} | prompt='{prompt[:40]}...'", flush=True)
            return False

        content = cls.format_problem_solution_episode(session_id, prompt, decision, loc, cost, solution_text)
        tags = [session_id, decision, "tierbridge_auto_ingest"]
        if loc > 0:
            tags.append("code_modified")
        if is_first_turn:
            tags.append("initial_request")

        # 1순위: sub_memory 파이썬 패키지 직결 호출
        try:
            from sub_memory.service import MemoryService
            service = MemoryService()
            await asyncio.to_thread(service.store_memory, content=content, tags=tags)
            print(f"➔ [MEMORY:STORED] [In-Process Service] session={session_id[:8]} [{decision}] loc={loc} lines | cost=${cost:.4f}", flush=True)
            return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Service store failed, falling back to SQLite: {e}")

        # 2순위: 로컬 SQLite DB(memory.db) 직접 Insert Fallback (100% 무중단 적재 보장)
        try:
            db_path = cls.get_db_path()
            await asyncio.to_thread(cls.store_to_sqlite, db_path, content, tags)
            print(f"➔ [MEMORY:STORED] [SQLite Direct] session={session_id[:8]} [{decision}] loc={loc} lines | cost=${cost:.4f} | db={db_path}", flush=True)
            return True
        except Exception as e:
            print(f"➔ [MEMORY:ERROR] session={session_id[:8]} failed: {e}", flush=True)
            return False

### 3.2 `harness.py` & `UsageTracker` 이벤트 연동 지점
* `UsageTracker.parse_and_track_from_buffer`에서 파싱된 `response_full_text`(LLM 최종 응답)를 `track_request(..., response_text=response_full_text)`로 온전히 전달:
  ```python
  event_data = {
      "session_id": session_id,
      "prompt": user_prompt,
      "decision": decision,
      "loc": loc_lines,
      "cost": cost_usd,
      "is_first_turn": is_first_turn,
      "solution": response_full_text
  }
  asyncio.create_task(MemoryIngestionWorker.process_log_event(event_data))
  ```

---

## 4. 후속 Step 연계 및 계승 구조 (Continuity)

1. **Step 2 (사전 기억 회수)**: Step 1에서 `[문제]-[해결책]`으로 구조화되어 저장되었으므로, Step 2에서 50ms 이내로 500토큰 이하의 알짜배기 정답 레퍼런스만 즉시 회수 가능.
2. **Step 3 (기억 가중치 재강화)**: Step 1에 보존된 `cost_usd`와 `decision`을 기반으로 고난도(`CHALLENGER`/`GOLD`) 지식 노드의 엣지 가중치를 3배 강화.
3. **Step 4 (크레딧 절감 대시보드)**: 회수된 지식 덕분에 메인 모델이 `GOLD ➔ BRONZE/SILVER`로 다운스케일링되어 아낀 실질 크레딧(Cr)을 대시보드에 연계 리포팅.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **Direct In-process 파이썬 임포트 테스트**:
   ```bash
   python -c "import asyncio; from src.tierbridge.memory_ingestion_worker import MemoryIngestionWorker; asyncio.run(MemoryIngestionWorker.process_log_event({'session_id': 'sess_test1', 'prompt': '테스트 지식 저장', 'decision': 'GOLD', 'cost': 0.12, 'is_first_turn': True}))"
   ```
2. **하네스 실시간 연동 테스트**:
   * `run_harness.sh` 가동 후 Codex CLI로 프롬프트 전송.
   * `memory.db` 또는 `sub-memory-web` 대시보드(`http://127.0.0.1:8765/ui`)에서 `sess_...` 태그와 함께 `store_memory` 노드가 자동 생성되었는지 확인.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step1_ingestion.md 문서를 바탕으로 Step 1 비동기 세션 로그 수집 파이프라인 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
