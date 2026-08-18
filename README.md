# ⚡ TierBridge

> **Codex & ChatGPT Enterprise 크레딧을 최대 70%까지 자동 절감해주는 스마트 LLM 라우팅 하네스 프록시**

TierBridge는 에이전트 CLI(Codex 등)와 OpenAI 백엔드 사이에서 동작하는 로컬 프록시입니다. 에이전트 코드 수정 없이 투명하게 동작하며, 질문의 복잡도를 실시간으로 평가하여 **최적의 모델과 추론 레벨(Reasoning Effort)을 6단계 게이밍 랭크 티어로 자동 스왑**해 크레딧을 대폭 절약합니다.

---

## 🚀 빠른 시작 (Getting Started)

### 1단계: 최초 1회 런타임 배포
개발 저장소에서 원클릭 배포 스크립트를 실행합니다. 배포가 완료되면 백그라운드 프록시가 가동되고 **글로벌 쉘 단축키(Alias)가 `~/.zshrc`에 자동 등록**됩니다:

```bash
./deploy.sh
```

> [!TIP]
> 배포와 동시에 현재 터미널에 환경 변수까지 한 번에 연결하고 싶다면 `source ./deploy.sh`로 실행하셔도 좋습니다.

---

### 2단계: 작업 터미널 세션 연결 (`tierbridge`)
새 터미널 창을 열거나 작업을 시작할 때, **어느 폴더에서든 `tierbridge` 한 줄만 입력**하면 현재 터미널 세션에 하네스 환경 변수가 즉시 주입됩니다:

```bash
tierbridge
```

---

### 3단계: 에이전트 CLI 실행
평소 사용하시던 Codex CLI를 그대로 실행하시면 스마트 라우터가 투명하게 작동합니다:

```bash
# [기본 모드] Standard 3-Tier 라우터 (BRONZE ~ DIAMOND 캡핑)
codex --oss --local-provider=ollama

# [고난도 모드] 4-Tier Sol 라우터 (최상위 CHALLENGER / gpt-5.6-sol 확장)
codex --oss --local-provider=ollama --model super
```

> [!NOTE]
> **💡 왜 공급자를 `ollama`로 지정해야 하나요?**  
> Codex CLI 바이너리가 지원하는 로컬 오픈소스 공급자 옵션은 `ollama`로 고정되어 있습니다. TierBridge는 에이전트 코드 수정 없이 `OLLAMA_HOST` 환경변수로 요청을 가로채어 작동하므로, `--local-provider=ollama`를 사용해야만 하네스 프록시의 스마트 라우팅 및 크레딧 절감 기능을 정상적으로 연결받을 수 있습니다.

---

### 4단계: 실시간 대시보드 및 로그 모니터링 (단축키 지원)
작업 중 소모된 토큰, 절감된 크레딧, 생성 코드 줄 수(LOC) 및 로그를 전용 단축키로 손쉽게 확인합니다:

```bash
# 📊 Kibana 스타일 3초 실시간 라이브 대시보드 열기
tierbridge-dash

# 📄 실시간 런타임 라우팅 로그 모니터링 (tail -f)
tierbridge-log
```

---

## 🎮 주요 기능 및 사용법 (Features & Usage)

### 1. 🎯 6단계 게이밍 RPG 랭크 티어 동적 라우팅
질문의 난이도를 실시간으로 판정하여 적합한 모델과 추론 강도로 자동 연결합니다:

* 🥉 **BRONZE** (`gpt-5.6-luna:low`): 단순 오타 수정, 명령어 안내, 파일 읽기/조회 스텝
* 🥈 **SILVER** (`gpt-5.6-luna:medium`): 표준 비즈니스 로직 단위 구현, 단일 파일 리팩토링
* 🥇 **GOLD** (`gpt-5.6-terra:medium`): 중간 복잡도 기능 구현, 컴포넌트 간 연동
* 💎 **PLATINUM** (`gpt-5.6-terra:high`): 복잡한 알고리즘, 다중 컴포넌트 아키텍처 설계
* 🔷 **DIAMOND** (`gpt-5.6-terra:extra_high`): 심층 디버깅 및 성능 튜닝 (3-Tier 모드 상한)
* 🏆 **CHALLENGER** (`gpt-5.6-sol:extra_high`): 데드락/메모리 누수 분석 (`--model super` 모드 상한)

> 📖 **[상세 기술 문서: 라우팅 하네스 & 6단계 랭크 설계 (routing_harness.md)](Controller/routing_harness.md)**

---

### 2. 📊 사용량 분석 & 실시간 웹 대시보드 (`analyze_usage.py`)
`harness.log`에 기록된 데이터를 정밀 분석하여 월별, 일자별, 세션별 통계와 3초 라이브 갱신 대시보드를 제공합니다.

```bash
# 실시간 엔터프라이즈 계정 잔여 크레딧 및 지출 한도 조회
./analyze_usage.py --balance
# 또는 독립 스크립트 실행
./check_credits.py

# 전체 통계 및 Top 크레딧 소모 프롬프트 요약 보고서 출력
./analyze_usage.py

# 특정 월(YYYY-MM) 단위 필터링
./analyze_usage.py --month 2026-08

# 특정 세션 ID 전용 필터링
./analyze_usage.py --session 5eb61a1e

# 3초 라이브 자동 갱신 웹 대시보드 생성 및 열기
./analyze_usage.py --html
```

* **실시간 엔터프라이즈 잔여 크레딧 조회 (`--balance` / `check_credits.py`)**: 백엔드 API를 직접 호출하여 실제 지출 한도, 누적 소모량, 잔여 크레딧(%) 및 리셋 일정을 실시간으로 즉시 파악합니다.
* **3초 라이브 오토싱크 (`#liveSyncBadge`)**: 브라우저를 열어두기만 해도 새 로그와 수치가 실시간 갱신됩니다.
* **크레딧 정밀 3분할 집계**: `전체 크레딧`, `메인 모델 크레딧`, `분류기 크레딧`을 분리 표시합니다.
* **생성 소스코드(LOC) 집계**: 모델 답변 내 마크다운 코드 블록 줄 수를 추출하여 개발 생산성을 측정합니다.

> 📖 **[상세 가이드: 대시보드 & 통계 분석기 사용 가이드 (analyze_usage_guide.md)](analyze_usage_guide.md)**  
> 📖 **[엔지니어링 명세서: 사용량 분석 & 대시보드 기술 명세 (analyze_usage.md)](Controller/analyze_usage.md)**  
> 📖 **[설계서: LOC 코드 라인 추출 및 생산성 지표 설계 (loc_tracker.md)](Controller/loc_tracker.md)**

---

### 3. 🩹 Model Healing Factor & 무중단 핫패칭
OpenAI/ChatGPT Enterprise 백엔드에 신규 모델이 출시되거나 단가 인하 패치가 이루어지면 자동으로 감지하여 원클릭으로 반영합니다.

* **신규 모델 자동 감지 배너**: 대시보드 상단에 `[ 💡 실제 신규 모델 감지됨! ]` 알림 자동 트리거
* **단가 & 성능 비교 모달**: 기존 활성 모델 vs 신규 추천 모델의 단가 차이 및 절감율 비교
* **원클릭 무중단 핫패치 (`POST /v1/models/heal`)**: 서버 재부팅 없이 `v1.1.0-healing-hotpatch`로 즉시 전환
* **원클릭 롤백 스위칭 (`POST /v1/models/version/switch`)**: 대시보드 드롭다운에서 이전 안정 버전으로 1초 만에 복원

> 📖 **[상세 기술 문서: Model Healing Factor & 버전 관리 스펙 (model_healing_factor.md)](Controller/model_healing_factor.md)**

---

### 4. 🏗️ 프로덕션 런타임 격리 배포 & 쉘 단축키 (`deploy.sh`)
개발 저장소(`$PWD`)와 실제 서비스 프록시 런타임(`~/.tierbridge/live`)을 분리하여 코드 수정이나 브랜치 변경 중에도 서비스가 안정적으로 유지됩니다.

```bash
# 개발 레포 ➔ 라이브 런타임 원클릭 동기화 및 무중단 재가동
./deploy.sh
```

#### 편리한 터미널 단축 명령어 (Shell Aliases)
`deploy.sh` 실행 시 `~/.zshrc`에 자동 등록되어 어느 경로에서든 사용 가능합니다:
* **`tierbridge`** : 런타임 하네스 가동 및 현재 터미널 세션에 환경 변수 주입
* **`tierbridge-credit`** : ChatGPT Enterprise 실제 계정 잔여 크레딧 및 한도 즉시 조회
* **`tierbridge-log`** : 라이브 프록시 가동 로그 실시간 모니터링 (`tail -f ~/.tierbridge/live/harness.log`)
* **`tierbridge-dash`** : Kibana 스타일 라이브 웹 대시보드 열기

> 📖 **[상세 기술 문서: 배포 아키텍처 및 환경변수 설정 명세서 (deployment_architecture.md)](Controller/deployment_architecture.md)**

---

## 🛠️ 트러블슈팅 & 문제 해결 (Troubleshooting)

자주 묻는 질문과 해결책은 전용 QA 가이드에서 확인하실 수 있습니다:

* **Q. 새 터미널 창을 열면 서버를 찾을 수 없다고 뜹니다.** ➔ `source run_harness.sh` 또는 `tierbridge` 입력
* **Q. 포트 18080에 프로세스가 2개 뜹니다.** ➔ Uvicorn Reloader(Watcher + Worker)의 정상 동작입니다.
* **Q. 모든 요청이 BRONZE로만 처리됩니다.** ➔ `/v1/responses` input 페이로드 파싱 및 인증 상태 확인

> 📖 **[트러블슈팅: 설정 및 문제해결 QA 전체 가이드 (troubleshooting_QA.md)](troubleshooting_QA.md)**

---

## 📑 전체 문서 허브 (Documentation Index)

| 카테고리 | 문서명 | 설명 |
| :--- | :--- | :--- |
| **🚀 시작 & 가이드** | [analyze_usage_guide.md](analyze_usage_guide.md) | USAGE 로그 분석기 및 CLI 옵션 사용 가이드 |
| | [troubleshooting_QA.md](troubleshooting_QA.md) | 구축/운영 중 직면한 트러블슈팅 사례 및 Q&A |
| **📐 코어 아키텍처** | [Controller/routing_harness.md](Controller/routing_harness.md) | 동적 라우팅 알고리즘, CLI 시점 분기 & 6단계 랭크 설계 |
| | [Controller/model_healing_factor.md](Controller/model_healing_factor.md) | 신규 모델 감지, 무중단 핫패칭 & 버전 스냅샷 관리 |
| | [Controller/deployment_architecture.md](Controller/deployment_architecture.md) | 런타임 격리 배포, Dual-Sink 보존 및 종합 환경변수 명세 |
| | [Controller/analyze_usage.md](Controller/analyze_usage.md) | 실시간 라이브 오토싱크, 크레딧 산출 및 대시보드 명세 |
| | [Controller/loc_tracker.md](Controller/loc_tracker.md) | 마크다운 코드 블록 LOC 추출 및 생산성 측정 설계 |
| **🧠 장기 기억 연동 (TBC)** | [Controller/integration_step1_ingestion.md](Controller/integration_step1_ingestion.md) | Step 1: 비동기 세션 로그 수집 & 퀄리티 게이팅 (예정) |
| | [Controller/integration_step2_recall.md](Controller/integration_step2_recall.md) | Step 2: 사전 기억 회수 & 50ms Strict 샌드박싱 (예정) |
| | [Controller/integration_step3_reinforcement.md](Controller/integration_step3_reinforcement.md) | Step 3: 비용/난이도 기반 기억 가중치 재강화 엔진 (예정) |
| | [Controller/integration_step4_analytics.md](Controller/integration_step4_analytics.md) | Step 4: 하네스 ✕ sub-memory 크레딧 시너지 분석 (예정) |
| **📈 성과 보고서** | [RESULT_REPORT.md](RESULT_REPORT.md) | 6단계 랭크 라우팅 및 하네스 최적화 최종 결과 보고서 |
| | [ROI_검토_지표.md](ROI_검토_지표.md) | 투자 대비 비용 절감 효과(ROI) 및 안정성 측정 가이드 |

---

## 🔮 향후 로드맵 (Upcoming Roadmap - TBC)

### 🧠 세션 턴별 장기 기억(sub-memory) 연동 및 연관 지식 자동 검색 (TBC)
* **세션 턴별 프롬프트 자동 수집**: 에이전트 대화 세션 중 의미 있는 비즈니스/아키텍처 턴의 프롬프트를 비동기로 자동 선별 수집.
* **초고속 연관 지식 검색 & 컨텍스트 주입**: 새로운 질문 인입 시 과거 세션에서 해결했던 관련 문제나 아키텍처 결정 사항을 5ms 이내로 초고속 검색하여 프롬프트 상단에 스마트 주입.
* **고난도 지식 가중치 재강화 & 크레딧 추가 절감**: 고비용(`CHALLENGER`/`DIAMOND`)으로 해결한 귀중한 트러블슈팅 지식을 장기 보존하고, 사전 기억 주입을 통해 후속 질문의 라우팅 난이도를 다운스케일하여 추가 크레딧을 절감하는 파이프라인이 탑재될 예정입니다. *(상세 설계: [Controller/integration_step1_ingestion.md](Controller/integration_step1_ingestion.md) ~ [step4_analytics.md](Controller/integration_step4_analytics.md))*

---

## 🛡️ License & Compliance
* **Documentation First Policy**: 도메인 로직 변경 시 `Controller/*.md` 명세서를 선제적으로 갱신합니다.
* **ChatGPT Enterprise API 호환**: WAF 호환 파라미터 정제 및 JWT 자격증명 자동 갱신을 지원합니다.
