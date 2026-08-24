# 📑 Step 3: 비용/난이도 기반 기억 가중치 재강화 엔진 & 잠재 연관 지식 힌트 제안

본 문서는 TierBridge 하네스에서 많은 크레딧과 비용(`cost_usd`), 고난도 추론(`CHALLENGER`/`PLATINUM`/`GOLD`)이 투입되어 해결된 핵심 대화/디버깅 턴을 감지하여, 로컬 SQLite `memory.db`의 `edges` 및 랭킹 점수를 강화하고, 검색 적합도가 다소 낮더라도 유용한 힌트를 함께 제안하는 **Step 3 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

1. **비용/난이도 기반 그래프 엣지 및 가중치 자동 강화 (Cost & Difficulty Reinforcement)**:
   - 고난도 등급(`CHALLENGER`/`PLATINUM`/`GOLD`) 및 고비용($0.05 이상) 해결 턴이 생성될 때, 직전 연관 지식 노드들과의 연결선(`edges` 테이블)을 자동 생성하고 `weight`를 승격(1.0 ➔ 3.0~10.0)하여 영구 보존.
   - 가중치 계산 산식:
     $$\text{Reinforce\_Weight} = \text{Base\_Weight} \times \left(1.0 + \frac{\text{cost\_usd}}{0.10} + \min\left(1.5, \frac{\text{loc}}{50}\right)\right) \quad (\text{최대 10.0 캡핑})$$
2. **잠재 연관 지식 힌트 제안 (Low-Score Exploratory Hinting)**:
   - 검색 스코어가 다소 낮거나(40%~60%) 약하게 연관된 과거 지식이라도 탈락시키지 않고, **"💡 혹시 참고할 만한 관련 과거 작업"** 섹션으로 분리하여 모델에게 함께 제공.
   - 모델이 사용자에게 *"직접적인 일치는 아니지만, 혹시 과거 진행했던 이러이러한 작업과 관련된 것일까요?"* 형태로 유연하게 제안할 수 있도록 유도.
3. **일원화된 비동기 원자적 파이프라인 (Atomic In-process Pipeline, < 5ms)**:
   - `MemoryIngestionWorker.process_log_event()` 저장 파이프라인 내부에서 `MemoryReinforcer.reinforce_node()`를 즉시 호출하여 0ms 추가 지연 없이 완벽한 원자적 갱신 보장.

---

## 2. 연동 아키텍처 및 흐름

```
[harness.py Turn Completed] ➔ [trigger_tracking()] ➔ [UsageTracker]
                                                           │
                                                           ▼ (asyncio.create_task)
                                            [MemoryIngestionWorker.process_log_event()]
                                                           │
                                            ┌──────────────┴──────────────┐
                                            ▼                             ▼
                                 [Insert Node & Memory]        [Check Cost & Decision]
                                            │                             │
                                            └──────────────┬──────────────┘
                                                           ▼
                                            [MemoryReinforcer.reinforce_node()]
                                                           │
                                            ┌──────────────┴──────────────┐
                                            ▼                             ▼
                               [Direct SQLite: Update edges]   [Boost Ranking Weights (<5ms)]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 신규 모듈 생성: `src/tierbridge/memory_reinforcer.py`
* **역할**: 비용/난이도/LOC 기반 가중치 계산 및 `~/.tierbridge/memory.db`의 `edges` 테이블 직접 갱신.
* **주요 메서드**:
  * `compute_reinforce_weight(cost_usd: float, decision: str, loc: int = 0) -> float`
  * `reinforce_node(db_path: str, node_id: str, cost_usd: float, decision: str, loc: int = 0) -> bool`
  * `link_related_edges(db_path: str, new_node_id: str, weight: float) -> int`

### 3.2 사전 회수 템플릿 개선: `src/tierbridge/memory_prefetcher.py`
* **주요 지식 (High Confidence, Score >= 60%)**: 상단에 즉시 브리핑용 핵심 지식으로 배치.
* **잠재 힌트 지식 (Low Score / Exploratory Hint, 35% <= Score < 60%)**:
  ```markdown
  ### [💡 보조 참고 힌트 (적합도: 45%)]
  - 과거 문제: ...
  - 해결 요약: ...
  - 안내 지침: 명확한 일치가 아닌 경우, 사용자에게 "혹시 이 작업과 관련된 내용인가요?" 형태로 가볍게 제안해 보세요.
  ```

### 3.3 검색 랭킹 보강: `src/tierbridge/memory_handler.py`
* `search_associated_memories()` 랭킹 산출 시 `edges.weight` 및 `cost_usd` 가중치를 추가 가산하여 고가치 지식이 상위에 안정적으로 랭크되도록 보정.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **단위 테스트 작성 (`test_memory_reinforcer.py`)**:
   * 가중치 계산 산식 검증 (비용, 결정 등급, LOC 복합 계산).
   * SQLite `edges` 테이블 생성, 엣지 가중치 승격 및 연결 정상 동작 검증.
2. **사전 회수 힌트 템플릿 검증 (`test_memory_prefetcher.py`)**:
   * 고적합도 지식과 저적합도 보조 힌트가 분리되어 마크다운에 정상 주입되는지 검증.
3. **전체 통합 회귀 테스트 (23+ tests passing)**.
