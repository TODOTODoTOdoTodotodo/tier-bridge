# Classifier Reserve & Fallback Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
TierBridge 하네스 프록시의 지능형 요청 분류기(Classifier)의 기본 모델을 고속 1.5x 우선 가속(`priority`) 및 별도 쿼터 풀을 가진 `gpt-reserve`로 전환하고, 쿼터 소진 또는 에러 발생 시 기존 `gpt-5.6-luna`로 자동 페일오버(Fallback)되는 고가용성 구조를 수립합니다.

또한, 분류기가 `gpt-reserve`를 사용했는지, 혹은 폴백으로 `gpt-5.6-luna`를 사용했는지를 터미널 로그(`harness.log`) 및 대시보드(Kibana Live Dashboard)에서 직관적으로 식별할 수 있도록 관측성(Observability)을 고도화합니다.

---

## 2. 아키텍처 및 흐름 (Architecture & Flow)

```
[Inbound Request]
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                 Router.classify_request                     │
│                                                             │
│ 1단계 (Primary): gpt-reserve 호출 (reasoning effort: low)   │
│   ├─ 성공 (HTTP 200 & 정상 토큰)                            │
│   │    └─ classifier_model = "gpt-reserve"                 │
│   │                                                         │
│   └─ 실패 (4xx, 429, 5xx, 타임아웃, 예외 발생)               │
│        ▼                                                    │
│ 2단계 (Fallback): gpt-5.6-luna 호출 (reasoning effort: low) │
│   ├─ 성공 (HTTP 200 & 정상 토큰)                            │
│   │    └─ classifier_model = "gpt-5.6-luna-fallback"       │
│   │                                                         │
│   └─ 실패 (양측 모두 실패 시)                               │
│        └─ classifier_model = "fail-safe" (기본 BRONZE 강하) │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     Observability & Sinks                   │
│                                                             │
│ * [DECISION: ...] ➔ [clf: gpt-reserve]                      │
│ * [USAGE] CLASSIFIER (gpt-reserve)                          │
│ * GET /v1/dashboard/stats ➔ classifier_status 반환          │
│ * Dashboard Header Badge ➔ [⚡ 분류기: gpt-reserve]          │
│ * Session Turn Table ➔ [CLASSIFIER ⚡reserve] 태그 표출     │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 세부 동작 규격 (Detailed Specifications)

### 3.1 라우터 페일오버 실행 규격 (`src/tierbridge/router.py`)
1. **1순위 호출 (Primary)**:
   - 대상 모델: `gpt-reserve`
   - 페이로드: `reasoning.effort = "low"`, `stream = True`
   - 1차 시도 실패 시 즉각 원인 로깅 (`➔ [CLASSIFIER] gpt-reserve 응답 지연/에러 감지 (HTTP {status}) ➔ luna 폴백 준비`)
2. **2순위 폴백 (Fallback)**:
   - 대상 모델: `gpt-5.6-luna`
   - `gpt-reserve`가 200 이외의 상태 코드(400, 404, 429 등)를 반환하거나 통신 예외 발생 시 즉각 실행.
3. **3순위 안전 강하 (Fail-safe)**:
   - 두 모델 모두 실패할 경우 무조건 `BRONZE` (`gpt-5.6-luna:low`)로 안전 강하하여 전체 세션 불통 방지.

### 3.2 로그 규격 (`harness.log` 및 터미널 출력)
1. **결정 로그 (DECISION)**:
   - `[{timestamp}]{sid} ➔ [DECISION: 4-TIER SOL ROUTER] BRONZE (gpt-5.6-luna:low) [clf: gpt-reserve] | "{prompt}"`
2. **사용량 로그 (USAGE CLASSIFIER)**:
   - `gpt-reserve` 성공 시:
     - `[{timestamp}]{sid} ➔ [USAGE] CLASSIFIER (gpt-reserve) | input={in} output={out} tokens | loc=0 lines | cost=${cost} USD`
   - `gpt-5.6-luna` 폴백 시:
     - `[{timestamp}]{sid} ➔ [USAGE] CLASSIFIER (gpt-5.6-luna-fallback) | input={in} output={out} tokens | loc=0 lines | cost=${cost} USD`

### 3.3 대시보드 API & UI 연동 규격
1. **API 규격 (`GET /v1/dashboard/stats`)**:
   ```json
   {
     "classifier_status": {
       "primary": "gpt-reserve",
       "fallback": "gpt-5.6-luna",
       "last_used": "gpt-reserve",
       "last_timestamp": "2026-09-23 10:15:00"
     }
   }
   ```
2. **대시보드 UI (`usage_dashboard.html` / `analyze_usage.py`)**:
   - **헤더 뱃지**: 상단 컨트롤 바에 `⚡ 분류기: gpt-reserve (폴백: luna)` 실시간 상태 뱃지 추가.
   - **세션 턴별 테이블**: 라우팅 등급 컬럼에서 `CLASSIFIER` 뱃지 표출 시 모델에 따라 `⚡reserve` (에메랄드) 또는 `luna` (스카이블루) 식별자 렌더링.
