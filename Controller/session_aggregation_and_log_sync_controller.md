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

### 2.4 결정 로그 정규식 매칭 실패 및 전역 프롬프트 버퍼 오염 결함
- `router.py`에 분류기 식별 태그(`[clf: gpt-reserve]`)가 추가되면서 로그 형태가 `[DECISION] TIER (model:effort) [clf: gpt-reserve] | "prompt"`로 변경됨.
- 기존 파서의 정규식 `\([^)]+\) \|`은 `[clf: ...]` 태그가 포함된 라인을 매칭하지 못하고 전부 누락(Skip)함.
- `prompt_history` 버퍼가 갱신되지 못하여, 직전 일자(9/22)의 마지막 프롬프트(`[Substep] [코드와 테스트는 통과했고... counter ...]`)가 버퍼에 남은 상태로 신규 세션의 모든 턴에 오염 복제됨.
- 세션 ID(`sid`) 기반의 개별 프롬프트 격리 매핑 부재로 인해 전역 버퍼의 이전 세션 잔여 값이 무차별 할당되는 구조적 결함 확인.

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

### 3.5 결정 로그 정규식 고도화 및 세션별 프롬프트 격리 규격
1. **정규식 고도화**:
   - `decision_pattern`: `(?:\s+\[clf:[^\]]+\])?\s*\|\s*\"(?P<prompt>.*)\"$` 패턴을 적용하여 `[clf: ...]` 태그 존재 여부 및 내부 큰따옴표가 포함된 긴 프롬프트도 무손실 파싱.
2. **세션별 프롬프트 격리 매핑**:
   - `session_prompts = {}` 매핑 테이블을 운용하여 `[DECISION]` 발생 시 `session_prompts[sid] = prompt`로 기록.
   - `[USAGE]` 매칭 시 해당 세션 ID의 최신 프롬프트를 1순위로 바인딩하여 세션 간 프롬프트 오염 원천 방지.

### 3.6 크레딧 중심 로깅(Credit-First Logging) 및 하위 호환 듀얼 파서 규격
1. **가변적 USD 로깅 제거 및 불변 물리량 중심 기록**:
   - 달러 단가는 OpenAI 정책, 캐시 할인, 모델 힐링에 따라 수시로 변동하므로 로그 라인에 고정 박제하지 않음.
   - 메인 모델 로그 규격:
     `[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | input={in_tok} output={out_tok} tokens | real_credit={delta_credit:.4f} | balance={curr_remaining:.2f} | loc={loc} lines`
   - 분류기 로그 규격:
     `[{now_str}]{sid_tag} ➔ [USAGE] CLASSIFIER ({classifier_model_used}) | input={clf_in_tok} output={clf_out_tok} tokens | loc=0 lines`
   - 백엔드 조회 실패 시 폴백 규격:
     `[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | input={in_tok} output={out_tok} tokens | loc={loc} lines`
2. **하위 호환 듀얼 파서 (Tolerant / Backward-compatible Parser)**:
   - `analyze_usage.py`의 `usage_pattern`은 과거 로그의 `cost=$... USD` 존재 여부를 Optional(`(?:\s*\|\s*cost=\$(?P<cost>[\d\.]+) USD)?`)로 수용함.
   - 신규 로그처럼 `cost` 문자열이 없는 경우, 기록된 `input_tokens` 및 `output_tokens`에 해당 모델의 최신 단가표([`config/model_versions.json`](file:///Users/HH191_1/Documents/agent-cli/config/model_versions.json))를 적용하여 집계 시점에 동적으로 USD 비용과 크레딧을 산출함.
3. **지표 표출 우선순위**:
   - CLI와 대시보드 모두 **크레딧(Credits)**을 제1 메인 지표로 삼고, USD는 참고용 환산 보조 지표로 표시함.

---

## 4. 검증 시나리오 (Verification Scenarios)
1. **CLI 세션 조회 검증**:
   - `python3 analyze_usage.py -s 01a0cbe5` 실행 시 추가 인자 없이 라이브 로그(`~/.tierbridge/live/harness.log`)를 자동 감지하여 10회 요청, 318,504 토큰, 6.16 Cr이 정상 표출되는지 검증.
2. **HTML 대시보드 렌더링 검증**:
   - `python3 analyze_usage.py --html --no-open` 실행 시 생성된 `usage_dashboard.html`에 `01a0cbe5` 세션이 드롭다운 최상단(`🔥 [최신]`)에 표출되는지 확인.
   - `sessionSelect`에서 `01a0cbe5` 선택 시 10턴 타임라인, KPI 카드(6.16 Cr, $0.5873, 10회 성사)가 정상 렌더링되는지 확인.
3. **충돌 방지 검증**:
   - `monthSelect`가 `2026-08`로 선택된 상태에서 `sessionSelect`를 `01a0cbe5`로 변경해도 데이터가 0건으로 사라지지 않고 정상 표출되는지 확인.
4. **크레딧 중심 신규 로그 파싱 검증**:
   - `cost=$... USD`가 생략된 신규 규격 로그 라인이 인입되어도 `analyze_usage.py`가 토큰 및 `real_credit` 기반으로 정확한 크레딧과 추정 비용을 누락 없이 집계하는지 검증.

