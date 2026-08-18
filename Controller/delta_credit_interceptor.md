# 💳 Delta Credit Interceptor (실시간 엔터프라이즈 크레딧 델타 인터셉터)

이 문서는 OpenAI ChatGPT Enterprise 백엔드의 실제 크레딧 차감액과 하네스 로컬 추정치 간의 오차를 0%로 완벽하게 동기화하기 위한 **실시간 델타 크레딧 인터셉터(Delta Credit Interceptor)**의 설계 및 구현 명세서입니다.

---

## 1. 개요 및 목적 (Overview & Goals)

1. **오차 없는 실제 크레딧 수집 (Zero-Drift Credit Tracking)**:
   * 추론 생각(Reasoning) 토큰, 프롬프트 캐싱 할인, 엔터프라이즈 정산 환율 등 백엔드의 비공개 과금 요소를 100% 반영하여 실제 차감된 정확한 크레딧($\\Delta \\text{Credit}$)을 기록합니다.
2. **사용자 응답 지연 0ms 보장 (Zero-Latency User Experience)**:
   * 클라이언트(Codex CLI)로 나가는 스트림 응답에 일절 지연을 주지 않기 위해, 크레딧 델타 측정은 **비동기 백그라운드 코루틴(`asyncio.create_task`)**으로 백단에서 처리합니다.
3. **이중 안전망 폴백 (Fault-Tolerant Fallback)**:
   * 일시적 네트워크 장애나 WAF 간섭으로 백엔드 크레딧 조회가 지연/실패할 경우, 기존의 **로컬 토큰 기반 단가 산출식(Token-based Estimator)**으로 자동 폴백하여 시스템 무중단성을 보장합니다.

---

## 2. 시스템 아키텍처 및 시퀀스 다이어그램 (Architecture & Sequence)

```
[Codex CLI]          [Harness Proxy]         [OpenAI Backend API]
     │                      │                          │
     │ 1. User Prompt       │                          │
     ├─────────────────────►│ 2. Routing & Forward     │
     │                      ├─────────────────────────►│
     │                      │                          │
     │ 3. Stream Relay      │ 3. Stream Response       │
     │◄─────────────────────┼──────────────────────────┤
     │                      │ (Stream Completed)       │
     │                      │                          │
     │                      │ 4. Background Task Spawn │
     │                      │    (asyncio.create_task) │
     │                      │                          ▼
     │                      │   [Credit Interceptor]
     │                      │   - 1.0s Eventual Lag Buffer
     │                      │   - GET /backend-api/codex/usage
     │                      │   - Delta = used_after - used_before
     │                      │   - Log: [USAGE] actual_delta=...
```

---

## 3. 핵심 모듈 구성

### 3.1. `src/tierbridge/credit_interceptor.py` (`CreditInterceptor`)
* **`fetch_usage()`**: `~/.codex/auth.json`의 JWT 토큰을 이용해 `https://chatgpt.com/backend-api/codex/usage`를 비동기 호출.
* **`track_turn_delta(session_id, prompt_summary, model, effort, local_tokens, local_cost)`**:
  * 스트림 종료 후 1.0초 유예(`asyncio.sleep(1.0)`)를 두고 백엔드 `used`를 조회.
  * 이전 누적치(`last_known_used`)와의 차이($\\Delta \\text{Credit}$)를 산출.
  * 만약 $\\Delta \\le 0$ (지연 반영)인 경우 로컬 추정 크레딧으로 보정하고 차기 턴에서 윈도우 보정.
  * 결과를 `➔ [USAGE]` 로그에 실시간 기록.

### 3.2. 로그 포맷 규격
```text
[2026-08-18 16:45:00] [sid: 5eb61a1e] ➔ [USAGE: GOLD] in=2,500 out=450 tokens | real_credit=0.1524 | balance=1380.15 | cost=$0.030480 USD
```

---

## 4. 대시보드 및 리포터 연동

1. **`analyze_usage.py`**:
   * 로그 파서가 `real_credit` 필드를 우선적으로 수집하여 실제 과금 통계를 산출.
   * `--balance` / `-b` 플래그로 언제든지 실제 엔터프라이즈 잔여 한도 확인.
2. **`usage_dashboard.html`**:
   * 대시보드 상단에 **[Enterprise Live Balance 게이지 위젯]** (한도, 소모량, 잔여량, 리셋일) 실시간 렌더링.
