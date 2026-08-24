# 📑 [설계 명세서] 하네스 ✕ Giyeok 기억저장소 통합 대시보드 및 MemoryHandler

본 문서는 `sub-memory-bootstrap` (Giyeok) 장기 기억 저장소에 축적된 문제-해결 지식 에피소드를 하네스 웹 대시보드(`usage_dashboard.html` / `tierbridge-dash`)에서 직접 탐색, 검색 및 통계 모니터링할 수 있도록 지원하는 **기억저장소 통합 대시보드 및 `MemoryHandler` 설계 명세서**입니다.

---

## 1. 아키텍처 및 SOLID 원칙 기반 객체 분리 설계

```
                 ┌────────────────────────────────────────────────────────┐
                 │         🧠 MemoryHandler (전용 비즈니스 레이어)          │
                 │         (src/tierbridge/memory_handler.py)             │
                 │  - get_recent_memories(limit, session_id)              │
                 │  - search_associated_memories(query, limit)            │
                 │  - get_memory_stats() (총 기억 수, 태그 수, 코드 수정율) │
                 └───────────▲────────────────────────────────▲───────────┘
                             │                                │
               [1. 실시간 3초 API 호출]                 [2. 정적 HTML 대시보드 빌드]
                             │                                │
              ┌──────────────┴──────────────┐   ┌─────────────┴─────────────┐
              │         harness.py          │   │      analyze_usage.py     │
              │  (FastAPI 라우팅만 담당)     │   │   (대시보드 UI/JS 생성)    │
              │  - /v1/dashboard/memories   │   │   - client_memories 주입  │
              │  - /v1/dashboard/memories/..│   └───────────────────────────┘
              └─────────────────────────────┘
```

* **단일 책임 원칙 (SRP)**:
  * `harness.py`: 프록시 라우팅 및 얇은 HTTP 엔드포인트 디스패처 역할만 수행.
  * `src/tierbridge/memory_handler.py`: `sub_memory.service.MemoryService` 및 SQLite `memory.db`와의 연결, 시맨틱/키워드 검색, 통계 산출 로직을 전담.
  * `src/tierbridge/memory_ingestion_worker.py`: 인바운드 세션 로그 수집 및 1차 퀄리티 게이트 필터링 전담.

---

## 2. API 엔드포인트 규격 (`harness.py`)

### 2.1 최근 기억 목록 조회 (`GET /v1/dashboard/memories`)
* **Query Params**: `limit` (기본값 50), `session_id` (선택 사항)
* **Response (JSON)**:
  ```json
  {
    "status": "success",
    "total_count": 12,
    "memories": [
      {
        "id": 1,
        "session_id": "019ffec0-eef3-7692-801c-60dae4e386bd",
        "decision": "GOLD",
        "loc": 42,
        "cost": 0.1523,
        "problem": "jCustNo 필드를 affCustNo로 변경하고 암호화 분기를 우회해줘",
        "solution": "GOLD",
        "tags": ["019ffec0-eef3-7692-801c-60dae4e386bd", "GOLD", "tierbridge_auto_ingest", "code_modified"],
        "created_at": "2026-08-20 10:15:30"
      }
    ]
  }
  ```

### 2.2 연관 기억 실시간 시맨틱 검색 (`GET /v1/dashboard/memories/search?q={query}`)
* **Query Params**: `q` (검색어/질의문), `limit` (기본값 10)
* **Response (JSON)**:
  ```json
  {
    "status": "success",
    "query": "Lombok 호환",
    "results_count": 3,
    "results": [
      {
        "id": 1,
        "score": 0.92,
        "session_id": "019ffec0-eef3",
        "decision": "GOLD",
        "content": "[Session: ...] [Decision: GOLD] ...",
        "tags": ["GOLD", "code_modified"]
      }
    ]
  }
  ```

### 2.3 기억 통계 지표 조회 (`GET /v1/dashboard/memories/stats`)
* **Response (JSON)**:
  ```json
  {
    "status": "success",
    "total_memories": 12,
    "total_tags": 18,
    "code_modified_count": 8,
    "structured_rate": 100.0
  }
  ```

---

## 3. 프론트엔드 UI/UX 설계 (`analyze_usage.py`)

1. **상단 탭 네비게이션 바**:
   * `[📊 AI 사용량 & 크레딧 관제]` ↔ `[🧠 Giyeok 장기 기억저장소 & 연관 검색]`
2. **기억저장소 탭 컴포넌트**:
   * **KPI 카드 4종**: 순수 지식 열매 수, 활성 도메인 태그, 최고 엣지 가중치, 지식 정형화율
   * **2단 분할 시맨틱 검색 & 생각나무 뷰포트**:
     * **좌측 (1/2)**: 실시간 검색창 & 검색 순위 카드 (1순위~5순위 일치도 및 💡 적용 해결책 미리보기, 🎯 그래프 포커스 버튼, ⚡ Neuralizer 소각 버튼)
     * **우측 (1/2)**: 콤팩트 성단 미니 그래프 (노드 크기/선 굵기 시너지 반영, 중앙 맞춤 및 물리엔진 토글, ⛶ 전체 화면 확대 버튼)
   * **전체화면 듀얼 뷰포트 (Dual Viewport)**:
     * `[🌌 성단 네트워크 (vis-network)]` ↔ `[🌿 생각나무 마인드맵 (Markmap)]` 원클릭 모드 전환
   * **실시간 기억 스트림 테이블**: 검색 및 세션 필터와 실시간 연동되어 전체 지식 이력을 투명하게 테이블로 표출.

---

## 4. 검증 절차 (Verification Steps)

1. **`MemoryHandler` 단위 테스트**: `test_memory_handler.py` 실행하여 최근 기억 조회, 검색, 통계 및 예외 Fallback 검증.
2. **대시보드 실시간 렌더링 검증**: `./analyze_usage.py --html --no-open` 실행 후 탭 전환, 듀얼 뷰포트 마크맵 및 검색 기능 정상 동작 확인.
