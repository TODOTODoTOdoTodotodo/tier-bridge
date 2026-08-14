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
- **Model Healing Factor & Dynamic Version Management (모델 힐링팩터 및 버전 롤백)**:
  - 신규 모델 릴리즈 및 토큰 단가 인하 자동 감지 엔진 (`HealingEngine`).
  - 대시보드 상에서 단가 비교표 확인 및 **원클릭 무중단 핫패치 (`POST /v1/models/heal`)** 지원.
  - 저장소 내 스냅샷 버전을 관리하여, 최신 힐링 적용 후 언제든지 과거 안정된 버전으로 복원하는 **원클릭 롤백 스위칭 (`POST /v1/models/version/switch`, `config/model_versions.json`)**.
- **Real-time Live Auto-Sync Web Dashboard (3초 자동 라이브 갱신)**:
  - 하네스 프록시의 `GET /v1/dashboard/stats` API와 연동하여 브라우저를 켜두기만 해도 3초 주기로 새로운 대화/토큰/크레딧 및 힐링 상태가 새로고침 없이 실시간으로 라이브 갱신됩니다.

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

## 🩹 Model Healing Factor System & 동적 버전 관리 (Version Rollback)

OpenAI/ChatGPT Enterprise 백엔드에 신규 모델이 추가되거나 토큰 단가가 인하되었을 때, 하네스는 무중단 핫패치와 롤백 스냅샷 버전 관리를 지원합니다.

```
[업스트림 신규 릴리즈 감지] ➔ [대시보드 단가 비교표] ➔ [원클릭 핫패치 POST /v1/models/heal] ➔ [config/model_versions.json 버저닝]
                                                                                            └── [원클릭 롤백 스위칭]
```

1. **실시간 신규 모델 감지 (`has_new_healing`)**:
   * 업스트림 API 탐색 결과 신규 모델 및 단가 절약 패치가 감지되면 대시보드 상단에 **`[ 💡 실제 신규 모델 감지됨! ]`** 알림 배너가 자동 활성화됩니다.
2. **단가 & 성능 비교표 모달 및 데모 테스트 (`[ 🧪 힐링 핫패치 데모 샘플 ]`)**:
   * 대시보드 우측 상단 데모 버튼을 클릭하여 현재 활성 모델 매핑 단가 vs 힐링 추천 모델 단가 비교표를 모달로 즉시 확인할 수 있습니다.
3. **무중단 원클릭 핫패치 (Hot-patching)**:
   * **[Apply Model Healing]** 버튼 클릭 시 하네스 서버 재부팅 없이 신규 스냅샷 버전(`v1.1.0-healing`)이 저장소에 등록되고 핫패치 라우팅이 즉시 가동됩니다.
4. **버전 관리 및 원클릭 롤백 (Version Snapshot & Rollback)**:
   * 대시보드 상단 **`[모델 버전: v1.0.0 (Active)]`** 드롭다운을 통해 언제든지 이전 버전 스냅샷으로 1초 만에 롤백/복원할 수 있습니다.

### 힐링 REST API 명세:
* `GET /v1/models/healing-status` : 힐링 감지 상태, 버전 목록 및 단가 비교표 반환
* `POST /v1/models/heal` : 힐링 신규 스냅샷 생성 및 무중단 핫패치 적용
* `POST /v1/models/version/switch` : 지정된 버전 ID(e.g., `v1.0.0`, `latest`)로 라우팅 롤백/복원

---

## 🏗️ 개발 저장소 ✕ 프로덕션 런타임 분리 아키텍처 & 배포 (`deploy.sh`)

개발자 개개인의 개발 저장소 위치가 어디든 상관없이, 실제 구동되는 하네스 프록시는 홈 디렉토리 하위의 독립 런타임 경로(**`$HOME/.tierbridge/live`**)에 격리 배포되어 가동됩니다. 개발 레포에서 소스코드를 편집하거나 브랜치를 교체하더라도 **현재 가동 중인 서비스 프록시에는 0% 영향**을 줍니다.

```
[개발 저장소 (Dev Workspace)]                  [실제 서비스 런타임 (Production Live)]
/path/to/any/agent-cli                         ~/.tierbridge/live/
 ├─ 소스코드 편집 & 단위 테스트                  ├─ harness.py (Port 18080 가동)
 ├─ 브랜치 전환 & 자유로운 실험                   ├─ harness.log (독립 수집)
 └─ ./deploy.sh 실행 ─── (안전 동기화 & 핫패치) ─► └─ harness.pid (프로세스 관리)
```

### 원클릭 배포 워크플로우:
```bash
# 개발 레포 소스를 $HOME/.tierbridge/live 에 동기화하고 백그라운드 프록시 안전 재가동
./deploy.sh
```

---

## 🚀 실행 및 연동 (원스텝 자동화)

포트 충돌 해제, 백그라운드 프록시 가동, 인증 패치, 환경 변수 주입까지 단 하나의 스크립트로 처리됩니다:

```bash
source run_harness.sh
```

`source` 명령어 실행 시 환경 변수(`OPENAI_BASE_URL`, `CODEX_API_BASE`, `OLLAMA_HOST`, `CODEX_OSS_PORT` 등)가 현재 터미널 세션에 자동으로 즉시 주입됩니다. 수동 설정 필요 없이 즉시 아래 명령어로 실행하실 수 있습니다.

```bash
# 기본 3-Tier 모드 가동
codex --oss --local-provider=ollama chat

# 4-Tier Sol 라우팅 모드 가동 (단축 인자 --model super 사용)
codex --oss --local-provider=ollama --model super chat
```

---

## ⚙️ 종합 환경변수 및 숨겨진 설정 레퍼런스 (Environment Variables)

TierBridge 하네스 및 연동 엔진에서 사용하는 전체 환경변수 및 숨겨진 설정 목록입니다:

| 환경변수 (Environment Variable) | 기본값 (Default) | 설명 (Description) |
| :--- | :--- | :--- |
| **`OPENAI_BASE_URL`** | `http://localhost:18080/v1` | Codex CLI가 하네스 프록시를 타도록 가로채는 인바운드 BASE URL |
| **`CODEX_API_BASE`** | `http://localhost:18080/v1` | Codex Enterprise 연동용 API 엔드포인트 BASE |
| **`OLLAMA_HOST`** | `http://localhost:18080` | Codex `--local-provider=ollama` 호스트 가로채기 |
| **`CODEX_OSS_PORT`** | `18080` | Codex 로컬 공급자 수신 포트 |
| **`ENTERPRISE_API_URL`** | `https://chatgpt.com/backend-api/codex/responses` | 업스트림 OpenAI Enterprise 백엔드 API 엔드포인트 |
| **`HARNESS_PORT`** | `18080` | 하네스 프록시가 바인딩하여 수신하는 로컬 포트 |
| **`AUTH_FILE_PATH`** | `~/.codex/auth.json` | 엔터프라이즈 JWT 인증 토큰 자동 파싱 경로 |
| **`SQLITE_VEC_PATH`** | `""` (자동 탐색) | `sub-memory-bootstrap` 벡터 확장 모듈 경로 |
| **`METRICS_LOG_PATH`** | `.sub-memory/metrics.jsonl` | 기억 회수 기여도 및 메트릭 수집 경로 |

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

* **세션 ID 동적 선택 드롭다운 UI & 세션 전용 랭킹 검색**: 대시보드 상단 세션 선택기(`sess_...`) 또는 검색창에 세션 ID 키워드를 입력하면, 해당 세션 내에서의 1, 2, 3위 **전용 랭크(Session-local Rank)**와 턴 기록이 즉시 필터링됩니다.
* **무제한 더보기 (Load More)**: 기본 Top 15개 턴이 노출되며, 하단 **`[ 🔽 더보기 ]`** 버튼을 눌러 15개 단위(16~30위...)로 전체 프롬프트를 확장하여 이어서 조회할 수 있습니다.
* **KPI Metric Cards**: Total Credits (1 Credit = $0.20 USD), Estimated Value ($), Total Tokens, Unique Sessions, LUNA Auto-scaling Savings ($ / Credits).
* **Top Credit Consuming Prompts**: 가장 많은 크레딧을 소모한 프롬프트/릴레이 턴 TOP 15 목록 및 등급 배치 인사이트.

---

## 📁 프로젝트 주요 구성 (Directory & Files)

- `harness.py` : 하네스 프록시 메인 서버 (FastAPI/Uvicorn, 모델 스왑, 힐링 API & 엔터프라이즈 JWT 헤더 주입)
- `analyze_usage.py` : 로그 파싱, 크레딧 집계, 월별/세션별 분석 및 Kibana 3초 라이브 웹 대시보드 리포터
- `config/model_versions.json` : 모델 버전 관리 스냅샷 저장소 및 active_version 포인터
- `run_harness.sh` : 프록시 원스텝 가동 및 터미널 환경변수 자동 주입 스크립트
- `src/tierbridge/` :
  - `router.py` : `substep_prompt` extraction, 3-Tier / 4-Tier Sol classification & dynamic effort mapping
  - `model_registry.py` : 모델 스냅샷 버저닝, 저장소 입출력 및 롤백 엔진
  - `healing_engine.py` : 신규 모델 감지, 단가 비교 매트릭스 도출 및 핫패치 릴리즈 엔진
  - `usage_tracker.py` : Zero-Drop token parser, LOC extractor & `[sid]` session logging
  - `stream_transpiler.py` : SSE 스트림 실시간 트랜스파일러
- `Controller/` :
  - `routing_harness.md` : 동적 라우팅 알고리즘 & 하네스 설계 명세 문서 (Documentation First)
  - `model_healing_factor.md` : Model Healing Factor & 버전 관리 스펙 명세 문서 (Documentation First)
  - `analyze_usage.md` : 사용량 통계, 크레딧 산출, Kibana 대시보드 & 오디팅 가이드 문서 (Documentation First)

---

## 🛡️ License & Rules Compliance

- Documentation First Policy 준수: 도메인 로직 변경 시 `Controller/*.md` 문서를 선제적으로 갱신합니다.
- ChatGPT Enterprise API 표준 준수: Incompatible parameter (`stream_options`) 자동 제거 및 JWT Token transparency 보장.
