# TierBridge

This document defines the dynamic routing strategy designed to optimize credits for Codex Enterprise models. It allows selecting between the **Standard 3-Tier Router** (BRONZE ➔ DIAMOND) and the **4-Tier Sol Router** (BRONZE ➔ CHALLENGER) at **Codex CLI execution time**.

## 1. System Architecture & Flow (CLI Execution-Time Router Selection)

```
[Codex Enterprise CLI]
 (e.g. codex --oss --local-provider=ollama [--model super])
             │
             │ 1. GET /v1/models (Health check & Model discovery)
             │ 2. POST /v1/chat/completions or /v1/responses (Payload contains 'model')
             ▼
┌─────────────────────────────────────────────────────────┐
│              LLM Routing Harness Proxy                  │
│                    (Port: 18080)                        │
│                                                         │
│ * Inspects incoming request 'model':                    │
│   - '--model super' / 'gpt-5.6-sol' / '4tier'           │
│     ➔ Activates 4-Tier Sol Router (BRONZE ➔ CHALLENGER) │
│   - Default ('gpt-5.4', 'gpt-5.6-terra', etc.)         │
│     ➔ Activates Standard 3-Tier Router (BRONZE ➔ DIAMOND)│
│ * Classifies query via gpt-5.6-luna (low effort).       │
│ * Logs dedicated [USAGE] CLASSIFIER credit tracking.    │
│ * Fetches dynamic mapping from ModelRegistry.           │
│ * Swaps target model & reasoning_effort dynamically.    │
│ * Injects Authorization: Bearer <access_token> header.  │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────┼──────────────┬──────────────┐
             ▼             ▼              ▼              ▼
          [BRONZE]      [SILVER]       [GOLD]       [CHALLENGER]
             │             │              │              │
       gpt-5.6-luna   gpt-5.6-luna  gpt-5.6-terra   gpt-5.6-sol
         (low)         (medium)       (medium)     (extra_high: 4-Tier만)
             └─────────────┴──────────────┴──────────────┘
                           │
                           ▼ Forward with Injected JWT Auth Header
                [Codex Enterprise API]
```

## 2. Model & Reasoning Effort Mapping Rules

### 2.1. Router Selection at CLI Execution Time (CLI 시점 라우터 선택)
하네스 서버는 별도 프롬프트나 모드 전환 없이 항시 백그라운드에서 실행되며, **Codex CLI 명령어의 `--model` 인자**에 따라 사용할 라우터를 동적으로 결정합니다.

* **기존 3-Tier 라우터 (Standard 3-Tier Router - 기본값)**:
  * **CLI 실행 명령**: `codex --oss --local-provider=ollama`
  * **라우팅 범위**: `BRONZE` (low) ~ `DIAMOND` (extra_high)
  * **특징**: `CHALLENGER` (`gpt-5.6-sol`) 모델을 사용하지 않고 `DIAMOND` (`gpt-5.6-terra`) 상한선으로 캡핑하여 회사의 크레딧을 철저히 보존합니다.

* **4-Tier Sol 라우터 (4-Tier Sol Router)**:
  * **CLI 실행 명령**: `codex --oss --local-provider=ollama --model super` (또는 `--model gpt-5.6-sol`)
  * **라우팅 범위**: `BRONZE` (low) ~ `PLATINUM` (high) ~ 최상위 **`CHALLENGER` (`gpt-5.6-sol` / extra_high)**
  * **특징**: 저난도 작업은 `BRONZE` / `SILVER`로 시작하는 스마트 동적 라우터를 유지하되, 최상위 고난도 작업(메모리 누수, 교착상태, 초대규모 분석) 발생 시 `CHALLENGER`까지 라우팅 영역을 확장합니다. 단축 인자 `--model super`로 직관적으로 호출할 수 있습니다.

> [!NOTE]
> **왜 `--local-provider=ollama`를 사용해야 하나요?**  
> 1. **Codex CLI 공급자 제약**: Codex 바이너리 내부에서 OSS 로컬 공급자로 지원하는 옵션값은 오직 `ollama`와 `lmstudio`로 고정되어 있습니다.  
> 2. **무수정 투명 가로채기**: TierBridge는 에이전트 수정 없이 `OLLAMA_HOST="http://localhost:18080"` 환경변수를 통해 Ollama 인바운드 요청을 가로채어 동작하므로, `--local-provider=ollama`를 지정해야만 하네스 프록시의 스마트 라우팅 및 크레딧 절감 기능을 적용받을 수 있습니다.

### 2.2. Gaming RPG Rank Tier Classification Table
특정 모델명(LUNA, TERRA, SOL)에 종속되지 않고 직관적이고 유연한 **게이밍 RPG 랭크 티어 체계 (BRONZE ➔ SILVER ➔ GOLD ➔ PLATINUM ➔ DIAMOND ➔ CHALLENGER)**를 적용합니다.

| Router Mode | Gaming RPG Rank | Destination Model (`v1.0.0`) | Reasoning Effort | Description / Typical Use Cases |
| :--- | :--- | :--- | :--- | :--- |
| **Common (1/4 & 2/4)** | 🥉 **BRONZE** | `gpt-5.6-luna` | `"low"` | Simple grammar, minor typos, command guide, simple file read |
| **Common (1/4 & 2/4)** | 🥈 **SILVER** | `gpt-5.6-luna` | `"medium"` | Standard business logic, single-file refactoring |
| **Common (2/4 & 3/4)** | 🥇 **GOLD** | `gpt-5.6-terra` | `"medium"` | Medium complexity, multi-component refactoring |
| **Common (2/4 & 3/4)** | 💎 **PLATINUM** | `gpt-5.6-terra` | `"high"` | Complex algorithms, multi-component architecture |
| **3-Tier Max** | 🔷 **DIAMOND** | `gpt-5.6-terra` | `"extra_high"` *(API: `"high"`)* | Deep debugging & tuning (3-Tier Mode Max Capped) |
| **4-Tier Max** | 🏆 **CHALLENGER** | `gpt-5.6-sol` | `"extra_high"` *(API: `"xhigh"`)* | Deadlock debugging, memory leak detection, deep kernel tuning (4-Tier Sol Mode Max) |

> [!IMPORTANT]
> 1. **Default 3-Tier Protection**: Running standard `codex --oss --local-provider=ollama` strictly limits maximum model consumption to **`DIAMOND` (`gpt-5.6-terra`)**.
> 2. **4-Tier Sol Elevation**: Specifying `--model super` (or `--model gpt-5.6-sol`) at CLI execution time expands the top-tier ceiling to **`CHALLENGER` (`gpt-5.6-sol` / `extra_high`)** while retaining low-tier `BRONZE` / `SILVER` savings for simple turns.

## 3. Dynamic Token Harvesting & Zero-Drop USAGE Policy
* Under `--oss` mode, the client does not send auth headers. The proxy dynamically harvests the active `access_token` from `~/.codex/auth.json` on every request. This ensures that token refreshes handled by the native ChatGPT login flow are transparently captured by the proxy.
* **Zero-Drop USAGE & Sub-step Cost Auto-scaling Policy**:
  1. **`/responses` Payload Sanitization**: Strips incompatible parameters like `stream_options` to prevent WAF / 400 Bad Request (`unknown_parameter`) errors from ChatGPT Enterprise backend API.
  2. **Session ID Tracking (세션 ID 구분 로깅)**: Extracts `conversation_id` / `session_id` from incoming request headers or payload and embeds `[sid: <session_id>]` tag in all `[DECISION]` and `[USAGE]` log entries to enable precise per-session credit auditing.
  3. **Sub-step Prompt Extraction (서브 스텝 비용 오토 스케일링)**: For intermediate agent relays (Turn 2+ tool-call steps), the proxy extracts the latest action/context prompt rather than recycling the initial turn prompt. This automatically downgrades simple sub-task steps (e.g. file editing, reading, command outputs) to **`BRONZE`**, saving up to 30-50% additional credits.
  4. **Multi-layer SSE Event Parser**: Extracts usage across diverse SSE response schemas (`response.usage`, `event.usage`, `prompt_tokens`, `input_tokens`).
  5. **Prompt-based Token Estimation Fallback**: If upstream SSE chunks omit usage or return 0 tokens (e.g. during specific tool-call steps), the proxy estimates input token count based on request payload text length, ensuring **100% of DECISION events are logged with valid USAGE records**.

## 4. Local Mock Verification Plan
* `/v1/models` route exposes `gpt-5.4-mini`, `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `4tier`, and `super`.
* `harness.py` inspects incoming request `model` dynamically.
* `run_harness.sh` starts standard proxy without requiring upfront interactive server prompts.
