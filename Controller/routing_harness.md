# TierBridge

This document analyzes the 3-tier routing strategy designed to optimize credits for Codex Enterprise gpt-5.6 family line-ups. It maps incoming CLI requests to appropriate model categories and dynamically tunes the `reasoning_effort` parameter based on task complexity, using `gpt-5.4-mini` as a quick router.

## 1. System Architecture & Flow (ChatGPT Auth Override)

```
[Codex Enterprise CLI / Client]
(auth_mode = "chatgpt" / --oss --local-provider=lmstudio)
             │
             │ 1. GET /v1/models (Health check)
             │ 2. POST /v1/chat/completions (without auth headers)
             ▼
┌─────────────────────────────────────────────────────────┐
│              LLM Routing Harness Proxy                  │
│                    (Port: 18080)                        │
│                                                         │
│ * Reads ~/.codex/auth.json in background to retrieve    │
│   active corporate JWT access_token.                    │
│ * Classifies query via gpt-5.4-mini.                    │
│ * Swaps model and reasoning_effort.                     │
│ * Injects Authorization: Bearer <access_token> header.  │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────┼──────────────┬─────────────┐
             ▼             ▼              ▼             ▼
          [MINI]      [LUNA:LOW/MED]  [TERRA:HIGH]  [TERRA:EXTRA_HIGH/MAX]
             │             │              │             │
       gpt-5.4-mini  gpt-5.6-luna   gpt-5.6-terra  gpt-5.6-terra
     (low / medium)  (low / medium)    (high)    (extra_high / max)
             └─────────────┴──────────────┴─────────────┘
                           │
                           ▼ Forward with Injected JWT Auth Header
                [Codex Enterprise API]
```

## 2. Model & Reasoning Effort Mapping Rules

| Classification | Destination Model | Reasoning Effort (`reasoning_effort`) | Description / Typical Use Cases |
| :--- | :--- | :--- | :--- |
| **MINI** | `gpt-5.4-mini` | `"low"` *(또는 원본 값 보존)* | Simple grammar, minor typos, command guide |
| **LUNA:LOW** | `gpt-5.6-luna` | `"low"` | Simple scripting, formatting changes |
| **LUNA:MEDIUM**| `gpt-5.6-luna` | `"medium"` | Standard business logic, refactoring |
| **TERRA:HIGH** | `gpt-5.6-terra`| `"high"` | Deep algorithms, multi-component architecture |
| **TERRA:EXTRA_HIGH**| `gpt-5.6-terra`| `"extra_high"` | Advanced debugging, system load tuning |
| **TERRA:MAX**  | `gpt-5.6-terra`| `"max"` | Deadlock debugging, latency optimization |

> [!IMPORTANT]
> 1. Standard `gpt-5.4` and `gpt-5.5` models are excluded from routing.
> 2. **`gpt-5.4-mini` 모델 역시 추론 레벨을 지원하므로**, 기존의 `pop`(언셋) 처리 정책을 폐지하고, `MINI` 등급으로 분류될 시 `reasoning_effort` 값으로 `"low"`를 할당하거나 클라이언트의 원본 본문 요청 값을 보존하여 전달합니다.
> 3. If the routing evaluation fails, the system automatically falls back to **`model="gpt-5.6-terra"`, `reasoning_effort="max"`** to guarantee execution stability.

## 3. Dynamic Token Harvesting Policy
* Under `--oss` mode, the client does not send auth headers. The proxy dynamically harvests the active `access_token` from `~/.codex/auth.json` on every request. This ensures that token refreshes handled by the native ChatGPT login flow are transparently captured by the proxy.

## 4. Local Mock Verification Plan
* `/v1/models` route responds with available model IDs to satisfy the LM Studio mock check.
* `/v1/chat/completions` parses the queries and routes accordingly.
