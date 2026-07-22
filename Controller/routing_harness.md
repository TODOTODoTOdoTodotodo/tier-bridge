# TierBridge

This document analyzes the 3-tier routing strategy designed to optimize credits for Codex Enterprise gpt-5.6 family line-ups. It maps incoming CLI requests to appropriate model categories and dynamically tunes the `reasoning_effort` parameter based on task complexity, using `gpt-5.6-luna` (low reasoning effort) as a fast and accurate router.

## 1. System Architecture & Flow (ChatGPT Auth Override)

```
[Codex Enterprise CLI / Client]
(auth_mode = "chatgpt" / --oss --local-provider=ollama)
             │
             │ 1. GET /v1/models (Health check)
             │ 2. POST /v1/chat/completions or /v1/responses
             ▼
┌─────────────────────────────────────────────────────────┐
│              LLM Routing Harness Proxy                  │
│                    (Port: 18080)                        │
│                                                         │
│ * Reads ~/.codex/auth.json in background to retrieve    │
│   active corporate JWT access_token.                    │
│ * Classifies query via gpt-5.6-luna (low effort).       │
│ * Swaps model and reasoning_effort.                     │
│ * Injects Authorization: Bearer <access_token> header.  │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────┼──────────────┬─────────────┐
             ▼             ▼              ▼             ▼
       [LUNA:LOW]     [LUNA:MEDIUM]  [TERRA:MEDIUM] [TERRA:HIGH/EXTRA_HIGH]
             │             │              │             │
       gpt-5.6-luna   gpt-5.6-luna   gpt-5.6-terra  gpt-5.6-terra
          (low)         (medium)        (medium)  (high / extra_high)
             └─────────────┴──────────────┴─────────────┘
                           │
                           ▼ Forward with Injected JWT Auth Header
                [Codex Enterprise API]
```

## 2. Model & Reasoning Effort Mapping Rules

| Classification | Destination Model | Reasoning Effort (`reasoning_effort`) | Description / Typical Use Cases |
| :--- | :--- | :--- | :--- |
| **LUNA:LOW** (Base / Fallback) | `gpt-5.6-luna` | `"low"` | Simple grammar, minor typos, command guide, simple scripting |
| **LUNA:MEDIUM**| `gpt-5.6-luna` | `"medium"` | Standard business logic, single-file refactoring, minor debugging |
| **TERRA:MEDIUM**| `gpt-5.6-terra`| `"medium"` | Medium complexity, multi-component refactoring, API integration |
| **TERRA:HIGH** | `gpt-5.6-terra`| `"high"` | Complex algorithms, multi-component architecture & design |
| **TERRA:EXTRA_HIGH**| `gpt-5.6-terra`| `"extra_high"` *(API: `"xhigh"`)* | Deadlock debugging, memory leak detection, deep system tuning (MAX Capped) |

> [!IMPORTANT]
> 1. Standard `gpt-5.4` and `gpt-5.5` models are excluded from routing.
> 2. **Base Minimum Model**: The minimum model is set to **`gpt-5.6-luna` (`low`)**. `gpt-5.4-mini` is excluded from request execution.
> 3. **Maximum Model & Effort Capping**: The maximum reasoning tier is capped at **`gpt-5.6-terra` (`extra_high`)**. `max` reasoning effort is mapped down to `"xhigh"` (`extra_high`) to prevent excessive credit burn.
> 4. **Cost-Efficient Fallback Policy**: If prompt evaluation is empty or routing fails, the system automatically falls back to **`model="gpt-5.6-luna"`, `reasoning_effort="low"`** to preserve company credits ($1,000 monthly limit).

## 3. Dynamic Token Harvesting Policy
* Under `--oss` mode, the client does not send auth headers. The proxy dynamically harvests the active `access_token` from `~/.codex/auth.json` on every request. This ensures that token refreshes handled by the native ChatGPT login flow are transparently captured by the proxy.

## 4. Local Mock Verification Plan
* `/v1/models` route responds with available model IDs to satisfy the Ollama/LM Studio mock check.
* `/v1/chat/completions` and `/v1/responses` parse queries and route dynamically per turn.
