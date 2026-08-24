# 🌐 [엔지니어링 로드맵] 전사 공유용 기억저장소 (Enterprise Shared Memory DB) 아키텍처 및 전환 검토서

## 1. 개요 및 비전
현재 TierBridge 기억저장소(`memory.db`)는 로컬 단일 사용자 SQLite 환경에서 34개의 순수 지식 열매를 안전하게 축적하고 50ms 이내 초고속 사전 회수(Pre-fetch Recall)를 수행하고 있습니다.
본 문서는 이를 **수십~수백 명의 엔지니어가 공유하는 전사적 집단 지성(Enterprise Collective Intelligence) 기억저장소**로 확장할 때 필요한 준비 작업, 기술적 리스크, 동시성/지연시간(Latency) 이슈 및 단계별 로드맵을 종합적으로 검토하고 규격화합니다.

---

## 2. 외부 DB 후보군 비교 및 아키텍처 제안

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                      전사 엔지니어링 에이전트 CLI (Codex, TierBridge Clones)              │
└────────────▲───────────────────────────────▲──────────────────────────────▲─────────────┘
             │ (1. L1 Local Cache: <2ms)     │ (2. L2 Async Sync)           │
┌────────────▼───────────────────────────────▼──────────────────────────────▼─────────────┐
│ 🚀 TierBridge Enterprise Hub (중앙 게이트웨이 & 지식 큐레이션 서버)                       │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│  • RBAC 권한 & PII 개인정보 마스킹 필터                                                  │
│  • 동시성 엣지 가중치 원자적 연산기 (Atomic Weight Engine)                               │
│  • 로컬 ➔ 전사 지식 승격 파이프라인 (Quality Gate: 엣지 가중치 2.0x 이상)               │
├──────────────────────────────┬─────────────────────────────┬─────────────────────────────┤
│ 1. Vector & Relational DB    │ 2. Graph Database           │ 3. In-Memory Cache          │
│    PostgreSQL + pgvector     │    Apache AGE / Neo4j       │    Redis Stack (TTL / Lock) │
│    (지식 에피소드 & 임베딩)    │    (생각나무 성단 & 연관성)   │    (50ms SLA 보장 캐시)     │
└──────────────────────────────┴─────────────────────────────┴─────────────────────────────┘
```

| DB 후보군 | 추천 조합 | 핵심 장점 | 고려 사항 |
| :--- | :--- | :--- | :--- |
| **1안 (최우선 추천)** | **PostgreSQL + `pgvector` + `Apache AGE`** | • RDB + 벡터 시맨틱 검색 + 그래프 쿼리(Cypher)를 **단일 인프라**로 완벽 통합<br>• 트랜잭션(ACID) 및 백업/보안 관리 용이 | 그래프 규모가 100만 건 이상일 때 인덱스 튜닝 필요 |
| **2안 (하이브리드)** | **Milvus / Qdrant + Neo4j** | • 수천만 건 이상의 초대규모 벡터 검색 및 복잡한 그래프 순회(Graph Traversal) 성능 극대화 | 두 개의 분산 DB를 관리해야 하므로 운영 복잡도 및 인프라 비용 증가 |
| **3안 (초고속 캐시형)** | **RedisVL (Redis Vector Library)** | • 1~3ms 미만의 극한 인메모리 지연시간 보장 (50ms 하네스 SLA 완벽 준수) | 메모리 비용 및 영구 영속성(AOF/RDB) 설정 필요 |

---

## 3. 핵심 검토 영역 및 예상 이슈 (Technical Challenges)

### 3.1 ⚡ 50ms 사전 회수(Pre-fetch Recall) SLA 및 네트워크 지연시간 (Latency)
* **현행 로컬 SQLite**: 인메모리/로컬 디스크 조회로 **0.5ms ~ 2ms** 내 완료.
* **원격 외부 DB 도입 시 리스크**:
  * 원격 네트워크 RTT (15~30ms) + 시맨틱 벡터 인덱스 검색 (15~25ms) 발생 시 **50ms Strict Timeout 샌드박스 초과 위험**.
* **해결 방안: 2-Tier Caching (L1 Local + L2 Central)**:
  * **L1 로컬 캐시 (SQLite/In-Memory LRU)**: 최근 사용된 핫(Hot) 지식 100~200개를 로컬에 복제 보존하여 1ms 내 즉시 회수.
  * **L2 중앙 원격 DB**: L1 미스 시 또는 백그라운드 비동기 풀링(Async Pull)으로 전사 신규 지식 동기화.

---

### 3.2 🔒 개인정보(PII) 마스킹 & 로컬 경로 오염 방지
* **문제점**:
  * 로컬 개발 경로(`/Users/HH191_1/Documents/...`), API 키, 내부 사번/토큰 등이 전사 DB에 무분별하게 적재될 경우 보안 침해 발생.
* **해결 방안**:
  * **Sanitization Filter (중앙 전송 전 필수 가동)**:
    1. 로컬 절대 경로를 프로젝트 루트 기준 상대 경로(`$REPO_ROOT/...`)로 정규화.
    2. Bearer 토큰, 패스워드, 이메일, 주민번호 등 정규식 패턴 자동 마스킹(`***MASKED***`).
    3. 네임스페이스 격리: `scope: "personal" | "team" | "company"`.

---

### 3.3 ⚔️ 다중 사용자 동시성 및 엣지 가중치 경합 (Concurrency & Race Condition)
* **문제점**:
  * 여러 개발자가 동시에 같은 쿠폰/GNB 지식을 참조할 때, `edges` 가중치 갱신(`weight = weight + 0.1`) 간 레이스 컨디션 발생.
* **해결 방안**:
  * **원자적 증가 (Atomic Increment 쿼리)**:
    ```sql
    INSERT INTO edges (source_id, target_id, weight, last_reinforced_at)
    VALUES ($1, $2, 1.1, NOW())
    ON CONFLICT (source_id, target_id)
    DO UPDATE SET weight = LEAST(edges.weight + 0.1, 3.0), last_reinforced_at = NOW();
    ```

---

### 3.4 🛡️ 권한 관리(RBAC) & 뉴럴라이저(Neuralizer) 소각 거버넌스
* **문제점**:
  * 한 개발자가 전사 공유 지식을 무단 소각하거나 잘못된 정보를 수정할 때의 권한 충돌.
* **해결 방안**:
  * **Soft Delete & 감사 로그 (Audit Trail)**:
    * `status: "ACTIVE" | "ARCHIVED" | "NEURALIZED"`
    * 누가, 언제, 어떤 사유로 소각했는지 이력 보존 (`neuralized_by`, `neuralized_at`, `reason`).
    * 관리자(Admin) 권한으로 30일 이내 원클릭 복구(Rollback) 지원.

---

### 3.5 🏆 지식 품질 퀄리티 게이트 & 전사 승격(Promotion) 파이프라인
* **단계별 지식 승격 흐름**:
  1. **개인 지식 (Local Private)**: 하네스 자동 수집 단계.
  2. **팀 지식 (Team Shared)**: 같은 리포지토리/프로젝트 내에서 2회 이상 성공적으로 재사용된 경우.
  3. **전사 표준 지식 (Company-wide Verified Fruit)**: 가중치 2.0x 이상 승격 및 리뷰어 검증 완료 시 전사 생각나무에 정식 편입.

---

## 4. 사전 준비 작업 체크리스트 (TODO Checklist)

- [ ] **Data Access Layer 인터페이스 추상화 (`BaseMemoryStore`)**:
  - `SQLiteMemoryStore`와 `PostgresMemoryStore`를 플러그 가능하도록 `src/tierbridge/storage/` 구조 분리.
- [ ] **비동기 임베딩 서비스 연동 (Batch Embedding Pipeline)**:
  - 전사 표준 텍스트 임베딩 모델(e.g., `text-embedding-3-small`, 1536차원) 규격화.
- [ ] **L1 로컬 ➔ L2 원격 백그라운드 동기화 데몬 (Sync Worker)**:
  - 오프라인 작업 시에도 로컬에서 정상 동작하고, 온라인 연결 시 중앙 DB로 Delta 증분 동기화.
- [ ] **전사 대시보드 멀티테넌시 UI 확장**:
  - 팀별/리포지토리별 필터 및 전사 지식 랭킹 뷰포트 지원.
