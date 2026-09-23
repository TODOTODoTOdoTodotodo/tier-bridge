# Session Aggregation & Log Synchronization Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
사용자가 실행한 최신 대화 세션(예: `01a0cbe5-af35-7472-b81f-bf3b3d192dbc`)이 `usage_dashboard.html` 웹 대시보드 및 CLI 분석기(`analyze_usage.py`)에서 정상 집계되지 않고 누락되는 문제를 해결합니다.

개발 레포지토리(`DEV_DIR`)와 독립 라이브 런타임(`LIVE_DIR`, `~/.tierbridge/live`) 간의 로그 탐색 우선순위를 정립하고, 대시보드 내 월별 필터(`monthSelect`)와 세션 필터(`sessionSelect`) 간의 충돌로 인한 데이터 유실(Data Wipe-out)을 방지하는 정밀 필터링 아키텍처를 수립합니다.

---

## 2. 근본 원인 분석 (Root Cause Analysis)

### 2.1 로그 소스 탐색 우선순위 결함
- 라이브 프록시(Port 18080)는 `~/.tierbridge/live/harness.log`에 실시간으로 요청 및 토큰 사용량을 기록함 (16,339줄 이상).
- 개발 디렉토리의 `/Users/HH191_1/Documents/agent-cli/harness.log`는 2026-08-13에 멈춘 구형 로그임 (3,618줄).
- `analyze_usage.py`의 `parse_args()`가 `script_dir/harness.log`를 기본값 1순위로 지정하여, 개발 디렉토리에서 스크립트를 실행할 경우 최신 9월 세션(`01a0cbe5` 등)이 포함되지 않은 8월 데이터만 분석/생성됨.

### 2.2 대시보드 자바스크립트 월-세션 필터 충돌 결함 (`renderDashboard`)
- `usage_dashboard.html`의 `renderDashboard(targetMonth, targetSession)`에서:
  ```javascript
  if (targetMonth && targetMonth !== 'ALL') {
      filteredRecords = filteredRecords.filter(r => r.month === targetMonth);
  }
  if (targetSession && targetSession !== 'ALL') {
      // 이미 targetMonth(예: 2026-08)로 걸러진 배열에서 9월 세션 검색 ➔ 0건 반환 (Wipe-out)
      filteredRecords = filteredRecords.filter(r => r.session_id === targetSession ...);
  }
  ```
- 상단 월 셀렉터가 `2026-08`로 되어 있는 상태에서 9월에 발생한 세션(`01a0cbe5`)을 선택하거나 `LATEST`를 조회하면 결과가 0건으로 사라지는 치명적 충돌 발생.

### 2.3 KPI 계정 실차감 vs 분류기 크레딧 합산 불일치
- 메인 모델 호출은 `real_credit`을 기록하지만, 보조 분류기(`CLASSIFIER`) 호출은 `cost` 기반으로만 기록됨.
- 대시보드 KPI 카드에서 `hasRealCredit` 조건 충족 시 `clfCredits`를 누락하고 `totalRealCredits`만 단독 표출하여, 세션 드롭다운(`6.16 Cr`)과 KPI 카드(`6.12 Cr`) 간 불일치 발생.

---

## 3. 상세 설계 및 해결 명세 (Detailed Architecture & Specifications)

### 3.1 로그 파일 탐색 우선순위 규격 (`analyze_usage.py`)
`analyze_usage.py`는 `ModelRegistry` 및 `MemoryHandler`와 동일하게 라이브 런타임 로그를 최우선 탐색하도록 개편합니다.

```
[로그 탐색 우선순위 (Priority Waterfall)]
1순위: 환경변수 TIERBRIDGE_LOG_PATH
2순위: ~/.tierbridge/live/harness.log (실시간 활성 라이브 로그)
3순위: $DEV_DIR/harness.log (개발 저장소 로컬 백업 로그)
4순위: ./harness.log (현재 작업 디렉토리)
```

### 3.2 세션 우선 필터링 & 월 동기화 규격 (`renderDashboard`)
1. **세션 우선 필터링 (Session-First Extraction)**:
   - `targetSession && targetSession !== 'ALL'`일 경우, `allRecords` 전체에서 해당 세션 레코드를 먼저 추출합니다.
   - `targetSession === 'LATEST'`인 경우, `allRecords` 전체를 스캔하여 가장 최근 타임스탬프를 가진 세션 ID(`latestSid`)를 동적으로 선출한 뒤 필터링합니다.
2. **월 셀렉터 자동 동기화 (Auto-sync Month Selector)**:
   - 특정 세션이 선택되었을 때, `monthSelect`의 값이 해당 세션의 월(`record.month`)과 불일치하면 `monthSelect.value`를 `'ALL'` 또는 해당 세션의 월로 자동 동기화하여 필터 충돌을 사전에 방지합니다.
3. **월별 필터는 전체 세션 조회 시에만 적용**:
   - `targetSession === 'ALL'`일 때에만 `targetMonth` 필터를 적용하여 기간별 조회를 보장합니다.

### 3.3 KPI 크레딧 계산 정합성 보장
- `displayCredits = (hasRealCredit && totalRealCredits > 0) ? (totalRealCredits + clfCredits) : totalCredits;`
- 실차감 크레딧(`totalRealCredits`)과 분류기 크레딧(`clfCredits`)을 합산하여 세션 목록의 `6.16 Cr`과 일치시킵니다.

### 3.4 라이브 ➔ 개발 환경 동기화 규격 (`deploy.sh`)
- `deploy.sh`에 배포/동기화 시 라이브의 최신 `harness.log`를 개발 레포지토리로 안전하게 갱신하는 보조 기능을 제공하여 개발 환경에서도 최신 대시보드를 즉시 검증할 수 있도록 지원합니다.

---

## 4. 검증 시나리오 (Verification Scenarios)
1. **CLI 세션 조회 검증**:
   - `python3 analyze_usage.py -s 01a0cbe5` 실행 시 추가 인자 없이 라이브 로그(`~/.tierbridge/live/harness.log`)를 자동 감지하여 10회 요청, 318,504 토큰, 6.16 Cr이 정상 표출되는지 검증.
2. **HTML 대시보드 렌더링 검증**:
   - `python3 analyze_usage.py --html --no-open` 실행 시 생성된 `usage_dashboard.html`에 `01a0cbe5` 세션이 드롭다운 최상단(`🔥 [최신]`)에 표출되는지 확인.
   - `sessionSelect`에서 `01a0cbe5` 선택 시 10턴 타임라인, KPI 카드(6.16 Cr, $0.5873, 10회 성사)가 정상 렌더링되는지 확인.
3. **충돌 방지 검증**:
   - `monthSelect`가 `2026-08`로 선택된 상태에서 `sessionSelect`를 `01a0cbe5`로 변경해도 데이터가 0건으로 사라지지 않고 정상 표출되는지 확인.
