# 📝 TierBridge Changelog

All notable changes to the TierBridge Enterprise AI Routing & Memory system will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.1.1] - 2026-08-27 (Official Baseline Release: Real Credits, Zero-Flicker UX, Git Sync & Polling Control)

### 🌟 Added
* **🏷️ System Versioning (`v0.1.1`)**:
  * TierBridge 공식 릴리즈 버전 관리 체계(`VERSION`, `src/tierbridge/version.py`, `GET /v1/version`) 구축 및 대시보드 타이틀 뱃지 연동.
* **🔄 Configurable Live Polling (기본 5초 & `localStorage` 영구 기억)**:
  * 실시간 대시보드 갱신 주기를 `3초`, `5초`, `10초`, `30초`, `수동(중지)`, `직접 입력`으로 세분화하고 새로고침 후에도 유지되도록 구현.
  * 즉시 새로고침(`[🔄]`) 및 일시정지(`[⏸️ / ▶️]`) 원클릭 퀵 컨트롤 툴바 탑재.
* **📦 Git Sync & Pull Status Detection (`git_sync_checker.py`)**:
  * 백그라운드 3분 캐싱 기반 원격 저장소(`origin`) 상태 자동 감지.
  * 신규 커밋 대기 시 `[🟡 N개 Pull 필요]` 뱃지 표시 및 커밋 목록/`git pull && ./deploy.sh` 원클릭 복사 모달 제공.
* **💳 OpenAI Enterprise Real Deducted Credits (`real_credit`) Integration**:
  * 프롬프트 캐싱(50~80% 절감)이 반영된 계정 실차감 크레딧을 메인 KPI, 시계열 선형 차트, 1턴 페어링, 도넛 차트 및 테이블 전체에 일원화.
* **📈 Zero-Flicker Chart & 1-Turn Pairing UX**:
  * `[분류기 + 모델]`을 1턴으로 지능형 묶음 처리하여 지그재그 파동 제거 및 진행 중 단독 분류기 레코드의 우측 토큰 선 곤두박질 원천 차단.
  * In-Place 데이터 갱신 및 Diffing으로 3초 폴링 시 Canvas 파괴 깜빡거림 100% 제거.
  * `[✨ 듀얼 뷰]`, `[💳 크레딧만]`, `[📦 토큰만]`, `[📈 누적 추이]` 원클릭 지표 스위처 및 범례 호버 스포트라이트 제공.
* **☀️ Complete Light & System Theme Optimization**:
  * 성단 네트워크 노드 텍스트의 라이트 모드 가독성(진한 블랙 + 4px 화이트 외곽선) 보정 및 탭/필드/헤더 전 영역 라이트 테마 전환.

---

## [0.1.0] - 2026-08-24 (Step 4: Thought-Tree Dual Viewport, Neuralizer & Full Documentation Hub)

### 🌟 Added
* **🌌🌿 Dual Viewport (성단 네트워크 ↔ 생각나무 마인드맵)**:
  * 전체화면 확대 모달 내에 물리 엔진 기반 **`[🌌 성단 네트워크 (vis)]`** ↔ D3 기반 접이식 **`[🌿 생각나무 마인드맵 (Markmap)]`** 듀얼 뷰포트 원클릭 전환 UX 구축.
  * 도메인별(쿠폰, GNB 툴팁, 여행네컷, 챌린지 피드 등) 지식을 Root ➔ Branch ➔ Leaf 계층형 마크다운 트리로 자동 변환 및 렌더링.
* **💻 MacBook Trackpad Smooth Zoom & 툴바 컨트롤러**:
  * 마우스 휠 없이도 맥북 트랙패드에서 **두 손가락 상/하 스크롤 줌 및 핀치 줌 제스처**를 즉각적이고 부드러운 스케일 변환(`markmapInstance.rescale()`)으로 매핑.
  * 상단 툴바에 `[🔍+ 확대]`, `[🔍- 축소]`, `[🔍 뷰 맞춤]`, `[📂 모두 펼치기]`, `[📁 모두 접기]` 원클릭 버튼 탑재 (성단 뷰에도 `[🔍+]`, `[🔍-]` 지원).
* **🔍 Markmap 인라인 상세 확인 및 소각 링크 연동**:
  * 마인드맵의 모든 지식 노드 제목 및 메타 라인에 **`[🔍 상세 확인]`** 및 **`[📖 에피소드 & 소각]`** 인터랙티브 링크 뱃지(`<a class="tb-node-link">`) 탑재.
  * 링크 클릭 시 전체화면 위로 최상단 상세 정보 모달(`#graphNodeModal`, `z-[60]`)이 즉시 팝업.
* **⚡ Neuralizer (기억 정밀 소각 시스템)**:
  * 잘못되거나 더 이상 유효하지 않은 지식을 클릭 한 번으로 **0ms 즉시 캔버스(성단 & 마인드맵)에서 소각 제거**하고 SQLite DB(`nodes`, `edges`, `memories`)에서 영구 삭제 (`POST /v1/dashboard/memories/neuralize/{id}`).
  * 소각 실행 시 마인드맵 SVG 트리 실시간 0ms 재연산 및 라이브 폴링 연동.
* **🔍 2단 분할 시맨틱 실시간 검색 UI & 콤팩트 미니 그래프**:
  * 키워드 입력 시 100ms 내 일치율 높은 1~5순위 기억 카드를 좌측에 렌더링하고, 카드 클릭 시 우측 미니 그래프 카메라가 1.5배 줌인 포커스 이동.
* **📂 문서 체계 전면 개편 (`docs/`)**:
  * 레포지토리 내 25개 문서를 `docs/` 하위 6대 카테고리(총 16개 핵심 문서 + `docs/archive/` 8개)로 완벽 재배치 및 모든 링크 무결성 동기화.

### 🧹 Cleaned
* 34개의 순수 지식 열매 보존 및 불완전한 레거시 더미 로그/툴 에러 재시도 단편 소각 정리.

---

## [1.1.0] - 2026-08-24 (Step 3: Memory Synergy Reinforcement & Model Healing Factor)

### 🌟 Added
* **🧠 Step 3: Synergy Edge Reinforcement Engine (`MemoryReinforcer`)**:
  * 연관 지식 재참조 시 엣지 가중치 강화 (`+0.1x` 가산, 최대 `3.0x` 승격, 15% 자연 감쇠) 및 `GET /v1/dashboard/memories/top-edges` 실시간 랭킹 API 구축.
* **🩹 Model Healing Factor & 무중단 핫패치**:
  * OpenAI / ChatGPT Enterprise 백엔드 신규 모델 릴리즈 및 단가 인하 자동 감지.
  * 원클릭 무중단 핫패칭(`POST /v1/models/heal` ➔ `v1.1.0-healing-hotpatch`) 및 1초 버전 롤백 스위칭(`POST /v1/models/version/switch`).
* **💳 Delta Credit Interceptor**:
  * OpenAI 백엔드(`https://chatgpt.com/backend-api/codex/usage`)의 실제 차감 크레딧($\Delta \text{Credit}$)을 비동기 백그라운드로 추적하여 실제 계정 과금액과 로컬 통계를 100% 일치.
* **🎨 3-Segment 테마 시스템 & 3초 라이브 오토싱크**:
  * `어두운 (Dark)` / `밝은 (Light)` / `시스템 기본 (System OS)` 3단 테마 원클릭 전환 및 3초 주기 라이브 자동 갱신 대시보드 구축.

---

## [1.0.0] - 2026-08-24 (Step 1 & 2: 6-Tier Routing Harness & Pre-fetch Memory Recall)

### 🌟 Added
* **🎯 6단계 게이밍 RPG 랭크 티어 라우팅 하네스**:
  * `BRONZE` (`luna:low`), `SILVER` (`luna:medium`), `GOLD` (`terra:medium`), `PLATINUM` (`terra:high`), `DIAMOND` (`terra:extra_high`), `CHALLENGER` (`sol:extra_high`) 6단계 난이도 자동 분기.
  * `gpt-5.6-luna:low` 분류기 라우터 전담 추적 (`➔ [USAGE] CLASSIFIER`).
* **📥 Step 1: Memory Ingestion Pipeline (`MemoryIngestionWorker`)**:
  * LLM 최종 해결책(`solution_text`)과 세션 로그를 비동기로 수집하여 `~/.tierbridge/memory.db`에 구조화 적재.
* **⚡ Step 2: 50ms Pre-fetch Recall (`MemoryPrefetcher`)**:
  * 50ms Strict Timeout Sandbox 내에서 과거 유사 문제 해결책을 회수하여 인바운드 프롬프트 컨텍스트에 안전하게 선행 투명 주입.
* **🚀 런타임 격리 배포 (`./deploy.sh`) & 4대 글로벌 단축키**:
  * `$HOME/.tierbridge/live` 독립 런타임 격리 배포 아키텍처.
  * `tierbridge`, `tierbridge-dash`, `tierbridge-log`, `tierbridge-credit` 글로벌 셸 별칭 제공.
* **🧪 단위 테스트 스위트 (25/25 통과)**:
  * 라우터, 인터셉터, 메모리 파이프라인(Step 1~4) 전체 단위 검증 완료.
