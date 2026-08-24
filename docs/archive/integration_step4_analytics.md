# 📑 Step 4: 하네스 ✕ Giyeok 통합 대시보드 시너지 분석 & 인터랙티브 노드 연결망 시각화

본 문서는 TierBridge 하네스의 사용량 로그(`harness.log`)와 SQLite `memory.db`의 `nodes`, `edges`, `memories` 데이터를 결합하여, 장기 기억 회수(Recall)로 인한 크레딧 절감(ROI) 지표와 기억 간 연상 구조("생각나무" 노드 연결망)를 인터랙티브하게 시각화하는 **Step 4 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

1. **인터랙티브 기억 노드 연결망 시각화 (Interactive Association Graph Network)**:
   - `vis-network` 물리 엔진을 탑재하여 `nodes`와 `edges` 간의 연상 연결망을 인터랙티브 캔버스로 렌더링.
   - **노드 색상/그룹**: 티어 등급별 구분 (`CHALLENGER`/`PLATINUM`/`GOLD`/`SILVER`/`BRONZE`).
   - **노드 크기/발광**: 가중치(`weight: 1.0x ~ 10.0x`) 및 코드 수정량(`LOC`) 비례.
   - **엣지 굵기/선**: `edges.weight` (1.0x ➔ 1px, 10.0x ➔ 6px).
   - **인터랙션**: 줌/팬/드래그, 노드 클릭 시 우측 상세 패널(`Problem & Solution Inspector`) 및 연관 하위 트리 하이라이팅.
2. **통합 크레딧 절감(ROI) 및 시너지 KPI 리포팅 (Synergy Analytics)**:
   - `harness.log`의 `[MEMORY:RECALLED]` 및 `[MEMORY:HINT]` 로그를 파싱하여 세션별 기억 회수 횟수(Recall Hits) 및 다운스케일 절감 크레딧(Saved Credits) 산출.
   - **KPI 카드 4종**:
     - `총 지식 에피소드` (Total Memories)
     - `기억 회수 적중 횟수` (Recall Hits)
     - `기억 주입 절감 크레딧` (Saved Credits, e.g. 14.8 Cr / $2.96)
     - `최고 엣지 가중치` (Max Edge Weight, e.g. 8.6x)
3. **🏆 고가치 지식 엣지 가중치 TOP 10 랭킹 위젯**:
   - `edges` 테이블에서 가장 높은 가중치를 획득한 상위 10개 핵심 지식과 직전 연관 노드 연결 상태를 실시간 표출.
4. **프롬프트 테이블 기억 배지 연동 (`🧠 Recalled` / `💡 Hint`)**:
   - 메인 사용량 테이블의 각 턴마다 기억 회수 여부를 시각적 배지로 표시.

---

## 2. 연동 아키텍처 및 데이터 흐름

```
[harness.log] (실시간 로그 파싱)                [~/.tierbridge/memory.db] (Direct SQLite)
  ├─ [USAGE: GOLD/SILVER]                         ├─ nodes (id, text, embedding, timestamp)
  ├─ [MEMORY:RECALLED]                            ├─ edges (source_id, target_id, weight)
  └─ [MEMORY:HINT]                                └─ memories (id, content, tags, created_at)
        │                                                           │
        └─────────────────────────────┬─────────────────────────────┘
                                      ▼
                        [MemoryHandler.get_graph_data()]
                        [MemoryHandler.get_memory_stats()]
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
   [GET /v1/dashboard/memories/graph]          [analyze_usage.py Dashboard Generator]
   (FastAPI 실시간 비동기 API)                 (Kibana풍 usage_dashboard.html)
                                                              │
                                                              ▼
                                               [🧠 인터랙티브 생각나무 시각화]
                                               [🏆 가중치 랭킹 & 크레딧 절감 KPI]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 `MemoryHandler` 그래프 데이터 추출 메서드 추가 (`src/tierbridge/memory_handler.py`)
```python
@classmethod
def get_graph_data(cls, limit_nodes: int = 50) -> Dict[str, Any]:
    """
    vis-network 렌더링용 nodes & edges 그래프 데이터셋 생성 (<5ms)
    """
```
* 노드 그룹, 레이블, 툴팁(`title`), 크기(`value`), 엣지 굵기(`width`) 데이터 구조화.

### 3.2 `harness.py` 실시간 그래프 엔드포인트 추가
* `GET /v1/dashboard/memories/graph` ➔ `MemoryHandler.get_graph_data()` 반환.

### 3.3 `analyze_usage.py` 및 `usage_dashboard.html` 대시보드 고도화
* `vis-network` CDN (`https://unpkg.com/vis-network/standalone/umd/vis-network.min.js`) 탑재.
* 기억 탭 내 **"🧠 생각나무 연상 기억 노드 연결망 (Association Network Graph)"** 인터랙티브 캔버스 렌더링.
* 노드 클릭 시 상세 모달/인스펙터 연동.
* 메인 프롬프트 테이블에 `🧠 Recalled` 및 `💡 Hint` 태그 배지 렌더링.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **그래프 데이터셋 추출 단위 테스트 (`test_memory_handler.py`)**:
   * `get_graph_data()` 호출 시 노드/엣지 데이터 형식 및 가중치 반영 검증.
2. **대시보드 생성 및 브라우저 검증**:
   * `./analyze_usage.py --html --no-open` 실행 후 `usage_dashboard.html`에서 인터랙티브 그래프 캔버스, 노드 클릭 인스펙터, 엣지 굵기 시각화 확인.
3. **전체 회귀 테스트 (24+ tests passing)**.
