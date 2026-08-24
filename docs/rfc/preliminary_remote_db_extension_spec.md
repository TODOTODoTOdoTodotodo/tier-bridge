# 🌐 [예비 기술 명세서 / RFC] 원격 DB 확장 및 전사 기억 동기화 아키텍처 (Preliminary Remote DB Extension Spec)

> 💡 **문서 목적 (Status: Draft / Proposed RFC)**:  
> 본 문서는 TierBridge 기억저장소를 전사 공유 시스템으로 확장할 때 참조할 **예비 기술 명세서(Preliminary Specification)**입니다. 향후 전사 프로젝트 승인 시 즉시 구현 및 확장이 가능하도록 아키텍처, 동기화 프로토콜, 경합 해결 정책 및 체크리스트를 정의합니다.

## 1. 핵심 아키텍처 철학: 로컬 퍼스트 (Local-First Zero-Latency)
런타임 프롬프트 인입 시마다 원격 DB를 직접 조회(Dynamic Remote Query)하면 네트워크 RTT(15~40ms)와 원격 부하로 인해 **50ms 사전 회수(Pre-fetch Recall) SLA가 위협**받을 수 있습니다.
따라서 **각 개발자의 머신에서는 로컬 SQLite(`~/.tierbridge/memory.db`)를 100% 독립적으로 사용하여 0.5ms 초저지연을 유지**하고, 전사 지식 공유는 **백그라운드 비동기 동기화(Background Asynchronous Sync)**로 처리하는 **로컬 퍼스트 분산 지식 아키텍처**를 채택합니다.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                   [개발자 A의 로컬 머신]                     [개발자 B의 로컬 머신]        │
│                ┌────────────────────────┐                ┌────────────────────────┐      │
│  프롬프트 ──►  │  TierBridge Harness    │  프롬프트 ──►  │  TierBridge Harness    │      │
│  (0.5ms 즉시)  └───────────▲────────────┘  (0.5ms 즉시)  └───────────▲────────────┘      │
│                            │ (0ms Local I/O)                         │ (0ms Local I/O)   │
│                ┌───────────▼────────────┐                ┌───────────▼────────────┐      │
│                │ 💾 Local SQLite DB     │                │ 💾 Local SQLite DB     │      │
│                │ (~/.tierbridge/memory) │                │ (~/.tierbridge/memory) │      │
│                └───────────▲────────────┘                └───────────▲────────────┘      │
└────────────────────────────┼─────────────────────────────────────────┼───────────────────┘
                             │                                         │
                 (1) Async Push: 내 지식 전송              (2) Async Pull: 전사 지식 수신
                 (백그라운드 비동기 / PII 마스킹)          (세션 시작 or 주기적 증분 복제)
                             │                                         │
                             ▼                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                    🏢 중앙 전사 지식 Hub (Central Enterprise Knowledge RDB)               │
│                                (PostgreSQL + pgvector)                                   │
│  • 전사 공유 지식 열매 (Company-wide Verified Fruits) 보존 및 인덱싱                       │
│  • 다중 머신 가중치 통계 및 퀄리티 게이트 (2.0x 이상 검증 지식 선별)                     │
│  • 소각(Neuralizer) 감사 로그 및 소프트 딜리트 상태 관리                                │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 양방향 비동기 동기화 메커니즘 (Bidirectional Sync Pipeline)

### 2.1 📤 Upstream Push (로컬 ➔ 중앙 RDB)
* **트리거 시점**: 세션 종료 시점, 에피소드 저장 완료 시점, 또는 주기적(5분 단위) 백그라운드 워커.
* **처리 절차**:
  1. **Sanitization Filter (로컬 선처리)**:
     - 절대 파일 경로(`/Users/HH191_1/...`) ➔ 프로젝트 루트 상대 경로(`$REPO_ROOT/...`) 변환.
     - Bearer 토큰, 사번, API Key 정규식 자동 마스킹(`***MASKED***`).
  2. **Push 페이로드 전송**:
     - `POST /v1/enterprise/sync/push`
     - 새로 생성된 노드 및 가중치 강화된 엣지 정보 전송.
  3. **소각(Neuralize) 동기화**:
     - 로컬에서 소각된 노드 ID는 중앙 RDB에 `is_deleted = true`, `neuralized_at = NOW()`로 비동기 반영.

### 2.2 📥 Downstream Pull (중앙 RDB ➔ 로컬 SQLite)
* **트리거 시점**: `tierbridge` 세션 시작 시점, 또는 30분~1시간 주기 백그라운드 폴링.
* **처리 절차**:
  1. **증분 쿼리 (Delta Query)**:
     - `GET /v1/enterprise/sync/pull?since={local_last_sync_timestamp}`
  2. **로컬 SQLite 병합 (Safe Merge / UPSERT)**:
     - 신규 전사 지식 노드: `INSERT OR IGNORE INTO nodes ...`
     - 엣지 가중치 병합: `weight = MAX(local_weight, central_weight)`를 취해 로컬과 전사 시너지를 안전하게 결합.
     - 전사 소각 노드: 중앙에서 `is_deleted = true`인 노드는 로컬 SQLite에서도 `DELETE` 처리.

---

## 3. 원격 DB Pulling 전략 및 데이터 경합 해결 정책 (Conflict Resolution Policies)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                      경합 발생 시나리오 및 해결 정책 (Conflict Matrix)                    │
├────────────────────────┬─────────────────────────────────────────────────────────────────┤
│ 시나리오               │ 해결 정책 및 알고리즘                                           │
├────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ 1. 엣지 가중치 충돌   │ 시너지 합산 공식: min(1.0 + Δlocal + Δremote, 3.0)              │
│ 2. 노드 본문 수정 충돌 │ LWW (최신 수정 우선) + 시맨틱 포킹 (신규 서브 노드 자동 분기)    │
│ 3. 소각 vs 참조 충돌   │ Tombstone(비석) 우선 소각 + 로컬 휴지통(Trash) 30일 보관       │
│ 4. 태그 및 메타 충돌   │ 합집합(Union Set) 병합: Tags_local ∪ Tags_remote                │
└────────────────────────┴─────────────────────────────────────────────────────────────────┘
```

### 3.1 ⏱️ Pulling 주기 및 네트워크 트래픽 제어 정책
1. **Session-Start Pull (세션 진입 시 1회 즉시 실행)**:
   * `tierbridge` 명령어로 터미널 세션 진입 시, 백그라운드 동기화 데몬이 1회 비동기 실행되어 최신 전사 지식을 로컬 SQLite로 복제.
2. **Adaptive Idle Pull (유휴 시간 적응형 폴링)**:
   * 개발자가 프롬프트 질의를 하지 않는 터미널 유휴 시간(Idle > 15분)에만 1회씩 경량 델타(`since={timestamp}`) 쿼리를 요청하여 작업 방해 0% 달성.
3. **지수 백오프 (Exponential Backoff for Offline Resilience)**:
   * 사내망/VPN 단절 시 재시도 간격을 1s ➔ 5s ➔ 30s ➔ 5m로 지연시키며, 에러 로그는 UI에 노출하지 않고 로컬에만 조용히 억제(Silent Fallback).

---

### 3.2 ⚔️ 데이터 경합 4대 해결 정책 (Conflict Resolution Rules)

#### [정책 1] 엣지 가중치 시너지 결합 (Edge Weight Merging)
* **문제점**: 로컬 개발자 A가 에피소드 1-2를 3회 재참조(`weight: 1.3`), 전사 다른 팀원들이 5회 재참조(`weight: 1.5`)했을 때 단순 덮어쓰기 시 어느 한쪽의 학습 이력이 유실됨.
* **해결 공식**:
  $$\text{Merged Weight} = \min\left(1.0 + (\text{weight}_{\text{local}} - 1.0) + (\text{weight}_{\text{remote}} - 1.0), \; 3.0\right)$$
  *(예: 1.0 + 0.3 + 0.5 = **1.8x** ➔ 팀과 개인의 시너지가 누적 승격됨)*

#### [정책 2] 노드 본문 수정 충돌 (Node Content Divergence)
* 동일한 `global_id`를 가진 노드의 문제 해결책 본문이 양쪽에서 서로 다르게 수정된 경우:
  1. `updated_at` 타임스탬프를 비교하여 **최신 수정본(Last-Write-Wins, LWW)**을 기본 채택.
  2. 만약 수정 내용의 시맨틱 유사도가 70% 미만으로 완전히 새로운 해법인 경우:
     * **시맨틱 포킹(Semantic Branching)**: 로컬 노드를 신규 UUID를 가진 대안 노드로 자동 복제 분기하고, 원본 노드와 `(weight: 1.1)` 엣지로 연결.

#### [정책 3] 소각(Neuralize) vs 로컬 참조(Usage) 충돌 (Tombstone 비석 정책)
* 전사 관리자나 팀원이 특정 노드를 중앙에서 소각(`is_deleted = true`)했으나, 로컬 개발자는 아직 해당 노드를 보존 중인 경우:
  1. 중앙의 **Tombstone(비석) 레코드**가 항상 우선하여 로컬 SQLite에서도 노드가 자동 `DELETE` 처리됨.
  2. 로컬 개발자의 예기치 않은 데이터 손실을 방지하기 위해, 소각 전 로컬 스냅샷을 `~/.tierbridge/trash/`에 30일간 백업 보존.

#### [정책 4] 도메인 태그 병합 (Tag Set Union)
* 전사 태그 `["MGTT-25938", "Gmarket"]`와 로컬 태그 `["Coupon_NPE", "Gmarket"]` 충돌 시:
  * 중복을 제거한 **합집합(`Set.union`)**으로 병합 ➔ `["MGTT-25938", "Gmarket", "Coupon_NPE"]`.

---

## 4. 로컬 SQLite 스키마 확장 (Schema Extension)

동기화 상태 및 Tombstone 추적을 위해 로컬 SQLite 테이블에 메타 컬럼을 추가합니다:

```sql
-- 1. nodes 테이블 확장
ALTER TABLE nodes ADD COLUMN global_id TEXT;         -- 전사 공통 UUID
ALTER TABLE nodes ADD COLUMN origin TEXT DEFAULT 'local'; -- 'local' | 'enterprise'
ALTER TABLE nodes ADD COLUMN sync_status TEXT DEFAULT 'pending'; -- 'synced' | 'pending'
ALTER TABLE nodes ADD COLUMN updated_at DATETIME;
ALTER TABLE nodes ADD COLUMN is_deleted BOOLEAN DEFAULT 0;

-- 2. 동기화 메타 테이블 신설
CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME
);
-- 예: ('last_pull_timestamp', '2026-08-24T16:00:00'), ('tombstone_sync_version', 'v12')
```

---

## 4. 핵심 예상 이슈 및 해결 방안 (Technical Challenges & Mitigations)

| 핵심 영역 | 예상 이슈 및 위험 | 아키텍처 해결 방안 (Mitigation) |
| :--- | :--- | :--- |
| **① 50ms 회수 SLA 및 지연시간** | 원격 DB 동적 쿼리 시 네트워크 RTT(15~30ms) 및 부하로 인한 **50ms 타임아웃 샌드박스 초과** 위험 | **Local-First SQLite 100% 분리**:<br>• 프롬프트 런타임은 로컬 SQLite만 조회하여 **0.5ms 초저지연 유지**<br>• 원격 DB는 오직 백그라운드 비동기(Async)로만 통신 |
| **② 개인정보(PII) & 로컬 경로 오염** | 개발자 개인 로컬 절대 경로(`/Users/HH191_1/...`), 인증 토큰, API 키가 전사 DB로 유출될 위험 | **Sanitization Filter (중앙 Push 전 로컬 필수 가동)**:<br>• 로컬 절대 경로 ➔ `$REPO_ROOT/...` 상대 경로 자동 변환<br>• Bearer 토큰, 패스워드, 사번 정규식 자동 마스킹(`***MASKED***`) |
| **③ 다중 머신 엣지 가중치 경합** | 여러 개발자가 동시에 동일 지식을 참조/강화할 때 중앙 RDB와 로컬 SQLite 간 `weight` 갱신 충돌 | **원자적 가중치 병합 (`MAX(local, central)`)**:<br>• 로컬과 전사 중 더 높은 가중치를 취해 시너지 보존<br>• 중앙 RDB는 `ON CONFLICT DO UPDATE SET weight = LEAST(weight + 0.1, 3.0)` |
| **④ 소각(Neuralize) 권한 거버넌스** | 한 개발자가 다른 팀원의 유효한 전사 공유 지식을 무단으로 소각(Neuralize)할 위험 | **Soft Delete & 감사 로그 (Audit Trail)**:<br>• `status: 'NEURALIZED'`, 소각자/사유 기록 보존<br>• 관리자 권한으로 30일 이내 원클릭 롤백(Rollback) 지원 |
| **⑤ 지식 품질 오염 & 스팸 방지** | 불완전한 작업 단편이나 저품질 프롬프트가 전사 생각나무를 오염시킬 위험 | **3단계 지식 승격 파이프라인 (Quality Gate)**:<br>1. 개인 로컬 ➔ 2. 팀 공유(2회 재사용) ➔ 3. 전사 표준 열매(가중치 2.0x 이상) |

---

## 5. 로컬 퍼스트 비동기 모델의 핵심 장점

1. **지연 시간 0ms 유지 (Zero Latency)**:
   - 프롬프트 인입 시 로컬 SQLite를 직접 조회하므로 **0.5ms 초저지연** 유지 (50ms 사전 회수 SLA 완벽 보장).
2. **100% 오프라인 동작 보장 (Offline-First Resilience)**:
   - 사내망/VPN이 끊기거나 비행기/외부 카페 등 오프라인 상태에서도 로컬 기억저장소는 완벽하게 동작.
   - 온라인 재접속 시 백그라운드 큐에 쌓인 동기화 페이로드가 자동으로 전송/수신됨.
3. **중앙 서버 장애 격리 (Fault Isolation)**:
   - 중앙 PostgreSQL 서버 점검이나 일시적 장애가 발생해도, 개별 개발자의 로컬 에이전트 작업에는 **영향도 0%**.
4. **점진적 퀄리티 게이트 적용 용이**:
   - 로컬에서 검증된 지식(반복 사용 및 가중치 1.5x 이상)만 선별하여 중앙으로 승격(Promote) 가능.

---

## 6. 준비 작업 체크리스트 (TODO Checklist)

- [ ] **로컬 동기화 백그라운드 워커 모듈 설계 (`src/tierbridge/sync_worker.py`)**
- [ ] **로컬 Sanitization 필터 구현 (로컬 절대 경로 상대화 & PII 마스킹)**
- [ ] **중앙 Enterprise Sync API 게이트웨이 엔드포인트 설계 (`POST /v1/enterprise/sync/push`, `GET /v1/enterprise/sync/pull`)**
- [ ] **중앙 PostgreSQL 스키마 정의 및 다중 머신 가중치 MAX 병합 로직 작성**
- [ ] **전사 대시보드 멀티테넌시 UI 확장 (전사 지식 / 팀 지식 / 내 지식 필터)**
