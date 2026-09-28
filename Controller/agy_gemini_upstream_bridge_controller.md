# Antigravity CLI (Agy) Gemini Bridge & Failover Controller Specification

## 1. 개요 및 배경 (Background & Objectives)
사내 ChatGPT Enterprise 계정의 워크스페이스 공용 크레딧 풀(`workspace_member_credits_depleted`)이 소진되었을 때, TierBridge 하네스 프록시(`http://localhost:18080`)를 경유하는 모든 코딩 에이전트(Codex CLI 및 기타 LLM 클라이언트)는 `HTTP 429 (usage_limit_reached)` 오류를 수신하여 진행 중이던 개발 컨텍스트와 대화가 중단됩니다.

이를 원천 해결하기 위해 로컬 개발 머신에 인증되어 있는 Google Antigravity CLI(`agy`)의 고성능 플래그십 모델인 **`gemini-3.8-flash-high`**를 TierBridge 하네스의 업스트림 백엔드로 연동하는 **Agy Gemini Bridge**를 구현합니다.

본 사양을 통해 사용자는:
1. 기존 하네스 포트(`18080`) 및 클라이언트 설정을 변경할 필요 없이 끊긴 컨텍스트를 즉시 이어나갈 수 있습니다.
2. 환경 변수(`UPSTREAM_PROVIDER=agy`)를 통해 Gemini 전용 모드로 고정하거나,
3. 기본 자동 페일오버 모드(`UPSTREAM_PROVIDER=auto`)를 통해 ChatGPT 429 발생 시 즉시 `gemini-3.8-flash-high`로 투명하게 전환되어 세션 중단 없는 고가용성(High Availability) 코딩 환경을 보장받습니다.

---

## 2. 지원 라우팅 옵션 및 환경 변수 (Configuration & Options)

| 환경 변수 / 옵션 | 설정 가능 값 | 기본값 | 동작 설명 |
| :--- | :--- | :---: | :--- |
| `UPSTREAM_PROVIDER` | `auto`, `agy`, `gemini`, `chatgpt` | `auto` | • `auto`: ChatGPT Enterprise 우선 시도 후 429(공용풀 고갈) 발생 시 `agy`로 즉시 투명 자동 전환<br>• `agy` / `gemini`: 모든 요청을 즉시 `agy` 백엔드로 직결<br>• `chatgpt`: 기존 ChatGPT Enterprise 전용 |
| `AGY_MODEL` | `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `claude-sonnet-4-6` 등 | `gemini-3.8-flash-high` | `agy` CLI 호출 시 사용할 모델 식별자 |
| 클라이언트 모델 플래그 | `--model gemini-3.8-flash-high`, `--model agy`, `--model gemini` | - | 클라이언트 실행 시점에 해당 모델명을 지정하면 공급자 설정과 무관하게 `AgyAdapter`로 즉시 분기 |

---

## 3. 상세 아키텍처 및 파이프라인 (Detailed Architecture)

```
[Agent Client (Codex / OpenAI API)]
         │
         ▼  (POST /v1/responses or /v1/chat/completions)
[TierBridge Harness (18080)]
         │
    ┌────┴───────────────────────────────┐
    │ 1. UPSTREAM_PROVIDER == 'agy'      │ ──► [AgyAdapter (gemini-3.8-flash-high)] ──► [agy CLI Subprocess]
    │    OR requested_model == 'gemini*' │                                                       │
    │ 2. UPSTREAM_PROVIDER == 'auto'     │                                                       │
    │    Try ChatGPT Enterprise          │                                                       │
    │    ├─► HTTP 200: Relay Stream ────┐│                                                       │
    │    └─► HTTP 429: Auto-Failover ───┼┴───────────────────────────────────────────────────────┘
    └───────────────────────────────────┘
                                         │
                                         ▼
                     [StreamTranspiler / SSE Formatter]
                     - /responses: response.output_text.delta + completed
                     - /chat/completions: choices[0].delta.content + [DONE]
                                         │
                                         ▼
                             [Client Output Streaming]
```

### 3.1 컨텍스트 및 대화 이력 보존 (Context Preservation)
- 클라이언트로부터 인입된 전체 대화 이력(`messages` 배열 또는 `/responses`의 `input` 구조체) 및 시스템 지시문(`instructions`, `SystemDirective`)을 정규화된 프롬프트로 병합.
- `MemoryPrefetcher`를 통해 인출된 세션 장기 기억(RAG 블록) 또한 프롬프트 컨텍스트에 온전히 유지하여 주입.

### 3.2 비동기 서브프로세스 스트리밍 엔진 (`AgyAdapter`)
- `asyncio.create_subprocess_exec('agy', '--model', model, '-p', full_prompt, stdout=PIPE, stderr=PIPE)`를 통해 논블로킹 비동기 프로세스 가동.
- 표준 출력(`stdout`)을 라인/청크 단위로 비동기 수신(`readline()`)하여 대기 지연 없이 즉시 클라이언트로 SSE 방출.

### 3.3 양방향 SSE 프로토콜 변환
- **Codex `/responses` 프로토콜 지원**:
  1. `data: {"type": "response.created", ...}`
  2. `data: {"type": "response.output_item.added", ...}`
  3. `data: {"type": "response.content_part.added", ...}`
  4. `data: {"type": "response.output_text.delta", "delta": "..."}` (스트리밍 본문)
  5. `data: {"type": "response.output_text.done", "text": "..."}`
  6. `data: {"type": "response.completed", "response": {...}}`
  7. `data: [DONE]`
- **표준 OpenAI `/chat/completions` 프로토콜 지원**:
  1. `data: {"choices": [{"index": 0, "delta": {"content": "..."}, "finish_reason": null}]}`
  2. `data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}`
  3. `data: [DONE]`

### 3.4 사용량 추적 및 대시보드 연동 (`UsageTracker`)
- `gemini-3.8-flash-high`에 대한 단가 등록 ($0.15 / $0.60 per 1M tokens).
- 응답 LOC 자동 산출 및 `harness.log`에 `[USAGE: AGY_BRIDGE] (gemini-3.8-flash-high)` 포맷으로 기록하여 대시보드 실시간 반영.

---

## 4. 검증 시나리오 (Verification Scenarios)
1. **Agy 서브프로세스 스트림 출력 검증**: `gemini-3.8-flash-high` 호출 및 청크 단위 비동기 수신 확인.
2. **`/v1/responses` 엔드포인트 E2E 스트리밍 검증**: TestClient를 통해 Codex CLI 규격 이벤트 순차 방출 확인.
3. **`/v1/chat/completions` 엔드포인트 E2E 스트리밍 검증**: OpenAI 규격 델타 청크 및 종료 시그널 확인.
4. **429 Auto-Failover 모의 검증**: 업스트림 429 인입 시 에러 중단 없이 Agy로 자동 전환되어 200 스트림 완성 확인.
