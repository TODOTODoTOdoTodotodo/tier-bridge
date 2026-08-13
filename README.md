# TierBridge

이 저장소는 Codex/ChatGPT 요청을 로컬 프록시로 받아서, 질문 난이도에 따라 모델과 추론 수준을 분류해 전달하는 하네스입니다.

---

## 💡 개요 및 목적

* 단순한 작업(명령어 안내, 단순 오타 수정, 파일 읽기/조회 스텝)은 저비용 저추론 모델(`LUNA:LOW`)로 보냅니다.
* 표준적인 비즈니스 로직 단위 구현 및 리팩토링은 `LUNA:MEDIUM`으로 처리합니다.
* 중간 이상의 복잡도 및 아키텍처 연동 작업은 `TERRA:MEDIUM` / `TERRA:HIGH` 단계로 라우팅합니다.
* 초대규모 분석, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅은 최상위 `SOL:EXTRA_HIGH` (`gpt-5.6-sol`)로 승격합니다.
* 로컬 인증 정보는 `~/.codex/auth.json`에서 자동으로 읽어 투명하게 엔터프라이즈 JWT 토큰을 주입합니다.

---

## 🔥 핵심 강점 및 특징 (Key Features & Strengths)

- **Zero-Code Agent Modification (에이전트 무손상 구동)**:
  - 에이전트 CLI 내부 코드나 설정을 전혀 수정할 필요가 없습니다. 
  - 환경 변수 가로채기(`OPENAI_BASE_URL` 등)를 통해 투명하게 작동하므로, 에이전트 고유의 프롬프트 흐름이나 툴 사용(MCP) 제어 로직을 100% 무손상 상태로 이식합니다.
- **Sub-step Cost Auto-scaling (서브 스텝 단위 비용 자동 강하)**:
  - 사용자 턴 내에서 에이전트가 툴(Tool Call)을 실행하고 코드를 편집/조회하는 릴레이 스텝(Turn 2+) 시 최신 서브 작업 텍스트(`substep_prompt`)를 정밀 추출하여 난이도를 재판정합니다.
  - 가벼운 서브 작업(파일 수정, 조회, 단순 스크립트 실행) 단계는 자동으로 **`LUNA:LOW`**로 강하되어 **추가 크레딧 절약율 30~50%를 제공**합니다.
- **Seamless Session Continuation (세션 컨텍스트 완벽 보존)**:
  - 하네스가 매 스텝마다 실시간으로 모델 ID를 교체(예: `gpt-5.6-luna` ➔ `gpt-5.6-terra`)하여 릴레이하더라도, 백엔드 레벨에서 동일한 대화 세션 ID(`conversation_id`)와 이전 누적 대화 기록이 완벽하게 보존됩니다.
- **Zero-Drop USAGE & Session ID (`[sid]`) Tracking**:
  - 업스트림 backend SSE 파서 강화 및 Prompt-based Fallback Token Estimator를 적용하여 backend 사용량 정보 유실 시에도 ** usage 기록 누락 0건 (Zero-Drop)**을 보장합니다.
  - 로그 라인마다 세션 ID 태그(`[sid: <session_id>]`)를 기록하여 대화 세션별 정밀 크레딧 오디팅이 가능합니다.
- **Kibana-Style Interactive Web Analytics Dashboard (`./analyze_usage.py --html`)**:
  - `analyze_usage.py` 실행 시 CLI 리치 표 보고서뿐만 아니라, 반응형 그래프(Chart.js)와 **동적 월 선택 Dropdown UI**가 포함된 **Kibana 다크테마 시각화 웹 대시보드 (`usage_dashboard.html`)**를 자동 생성하여 브라우저에 엽니다.

---

## 🛠️ 시스템 구조 (System Architecture)

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
│     ➔ Activates 4-Tier Sol Router (LUNA ➔ TERRA ➔ SOL)  │
│   - Default ('gpt-5.4', 'gpt-5.6-terra', etc.)         │
│     ➔ Activates Standard 3-Tier Router (LUNA ➔ TERRA)   │
│ * Classifies query via gpt-5.6-luna (low effort).       │
│ * Swaps target model & reasoning_effort dynamically.    │
│ * Injects Authorization: Bearer <access_token> header.  │
└──────────────────────────┬──────────────────────────────┘
                           │
             ┌─────────────┼──────────────┬──────────────┐
             ▼             ▼              ▼              ▼
       [LUNA:LOW/MID] [TERRA:MEDIUM]  [TERRA:HIGH] [SOL:EXTRA_HIGH]
             │             │              │              │
       gpt-5.6-luna   gpt-5.6-terra  gpt-5.6-terra   gpt-5.6-sol
         (low/med)       (medium)        (high)     (extra_high: 4-Tier만)
             └─────────────┴──────────────┴──────────────┘
                           │
                           ▼ Forward with Injected JWT Auth Header
                [Codex Enterprise API]
```

---

## 🎯 CLI 실행 시점 동적 라우터 선택 (3-Tier vs 4-Tier Sol Router)

하네스 서버는 별도 프롬프트나 서버 모드 전환 없이 항시 백그라운드에서 실행되며, **Codex CLI 실행 명령어의 `--model` 인자**에 따라 라우터 동작 방식이 동적으로 선택됩니다.

1. **기존 3-Tier 라우터 (Standard 3-Tier Router - 기본 실행)**:
   * **CLI 실행 명령**: `codex --oss --local-provider=ollama`
   * **라우팅 범위**: `gpt-5.6-luna` (low) ~ `gpt-5.6-terra` (extra_high)
   * **특징**: `sol` 모델을 소비하지 않고 `terra` 계열 상한선으로 캡핑하여 크레딧을 보존합니다.

2. **4-Tier Sol 라우터 (4-Tier Sol Router - `--model super` 단축 인자)**:
   * **CLI 실행 명령**: `codex --oss --local-provider=ollama --model super` *(또는 `--model gpt-5.6-sol`)*
   * **라우팅 범위**: `gpt-5.6-luna` (low) ~ `gpt-5.6-terra` (high) ~ 최상위 **`gpt-5.6-sol` (extra_high / API: `xhigh`)**
   * **특징**: 저난도 스텝은 `luna`로 크레딧을 절약하고, 메모리 누수/데드락 디버깅 등 최상위 고난도 작업 시 `gpt-5.6-sol`까지 라우팅 영역을 확장합니다.

---

## 📊 등급 체계 및 분류 기준 (Tier Classification)

| Router Mode | Classification | Destination Model | Reasoning Effort | Description / Typical Use Cases |
| :--- | :--- | :--- | :--- | :--- |
| **Common (1/4 & 2/4)** | **LUNA:LOW** | `gpt-5.6-luna` | `"low"` | Simple grammar, minor typos, file read/edit sub-steps |
| **Common (1/4 & 2/4)** | **LUNA:MEDIUM** | `gpt-5.6-luna` | `"medium"` | Standard business logic, single-file refactoring |
| **Common (2/4 & 3/4)** | **TERRA:MEDIUM** | `gpt-5.6-terra` | `"medium"` | Medium complexity, multi-component refactoring |
| **Common (2/4 & 3/4)** | **TERRA:HIGH** | `gpt-5.6-terra` | `"high"` | Complex algorithms, multi-component architecture |
| **3-Tier Max** | **TERRA:EXTRA_HIGH** | `gpt-5.6-terra` | `"extra_high"` | Deep debugging & tuning (3-Tier Mode Max Capped) |
| **4-Tier Max** | **SOL:EXTRA_HIGH** | `gpt-5.6-sol` | `"extra_high"` | Deadlock debugging, memory leak detection (4-Tier Sol Max) |

---

## 🚀 실행 및 연동 (원스텝 자동화)

포트 충돌 해제, 백그라운드 프록시 가동, 인증 패치, 환경 변수 주입까지 단 하나의 스크립트로 처리됩니다:

```bash
source run_harness.sh
```

`source` 명령어 실행 시 환경 변수 4개(`OPENAI_BASE_URL`, `CODEX_API_BASE`, `OLLAMA_HOST`, `CODEX_OSS_PORT`)가 현재 터미널 세션에 자동으로 즉시 주입됩니다. 수동 설정 필요 없이 즉시 아래 명령어로 실행하실 수 있습니다.

```bash
# 기본 3-Tier 모드 가동
codex --oss --local-provider=ollama chat

# 4-Tier Sol 라우팅 모드 가동 (단축 인자 --model super 사용)
codex --oss --local-provider=ollama --model super chat
```

---

## 📈 토큰/크레딧 분석 및 Kibana 시각화 웹 대시보드 사용법 (`analyze_usage.py`)

`harness.log`에 실시간 수집되는 `➔ [DECISION]` 및 `➔ [USAGE]` 이벤트 기반으로 크레딧, 토큰, LOC 및 프롬프트 인사이트를 정밀 파싱합니다.

### 1. CLI 요약 리포터 실행
```bash
# 전체 누적 통계, 월별/일자별/세션별 및 Top 프롬프트 인사이트 조회
./analyze_usage.py

# 특정 월(YYYY-MM) 단위 필터링 조회
./analyze_usage.py --month 2026-08

# 특정 날짜(YYYY-MM-DD) 단위 필터링 조회
./analyze_usage.py --date 2026-08-04

# 특정 세션 ID 필터링 조회
./analyze_usage.py --session 5eb61a1e
```

### 2. Kibana 스타일 동적 웹 대시보드 열기 (`--html` / `-w`)
```bash
./analyze_usage.py --html
```
명령 실행 시 Kibana 풍의 다크테마 웹페이지 (**`usage_dashboard.html`**)가 자동 생성되어 브라우저에 엽니다.

* **동적 월 선택 Dropdown UI**: 상단 드롭다운에서 월(`전체 월`, `2026-08`, `2026-07` 등)을 전환하면 KPI 카드, 일자별 추이 차트, 등급 분포 파이 차트, 프롬프트 인사이트 표가 실시간으로 동적 필터링됩니다.
* **KPI Metric Cards**: Total Credits (1 Credit = $0.20 USD), Estimated Value ($), Total Tokens, Unique Sessions, LUNA Auto-scaling Savings ($ / Credits).
* **Top Credit Consuming Prompts**: 가장 많은 크레딧을 소모한 프롬프트/릴레이 턴 TOP 15 목록 및 등급 배치 인사이트.

---

## 📁 프로젝트 주요 구성 (Directory & Files)

- `harness.py` : 하네스 프록시 메인 서버 (FastAPI/Uvicorn, 모델 스왑 & 엔터프라이즈 JWT 헤더 주입)
- `analyze_usage.py` : 로그 파싱, 크레딧 집계, 월별/세션별 분석 및 Kibana 웹 대시보드 리포터
- `run_harness.sh` : 프록시 원스텝 가동 및 터미널 환경변수 자동 주입 스크립트
- `src/tierbridge/` :
  - `router.py` : `substep_prompt` extraction, 3-Tier / 4-Tier Sol classification & dynamic effort mapping
  - `usage_tracker.py` : Zero-Drop token parser, LOC extractor & `[sid]` session logging
  - `stream_transpiler.py` : SSE 스트림 실시간 트랜스파일러
- `Controller/` :
  - `routing_harness.md` : 동적 라우팅 알고리즘 & 하네스 설계 명세 문서 (Documentation First)
  - `analyze_usage.md` : 사용량 통계, 크레딧 산출, Kibana 대시보드 & 오디팅 가이드 문서 (Documentation First)

---

## 🛡️ License & Rules Compliance

- Documentation First Policy 준수: 도메인 로직 변경 시 `Controller/*.md` 문서를 선제적으로 갱신합니다.
- ChatGPT Enterprise API 표준 준수: Incompatible parameter (`stream_options`) 자동 제거 및 JWT Token transparency 보장.
