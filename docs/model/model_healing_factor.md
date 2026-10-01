## 1. 개요 및 목적 (Background & Objectives)

LLM 모델 라인업(OpenAI/ChatGPT Enterprise 등)은 빠른 주기로 신규 모델(e.g., `gpt-5.7`, `gpt-5.6-luna-2026-08`)이 추가되거나 입력/출력 토큰 단가 인하 패치가 이루어집니다.

`Model Healing Factor System`은 다음을 목적으로 설계되었습니다:
1. **실제 신규 모델 및 단가 인하 실시간 감지**: 실제 업스트림 API에서 신규 모델이 릴리즈되었을 때만 대시보드 상단 알림 배너(`has_new_healing: true`) 자동 트리거.
2. **데모 샘플 테스트 버튼 (`[ 🧪 힐링 핫패치 데모 샘플 ]`)**: 핫패치 및 롤백 기능 동작을 검증할 수 있는 샘플 테스트 모달 별도 분리 제공.
3. **원클릭 하네스 모델 교체 (Healing Hot-patch)**: 사용자가 대시보드 상에서 버튼 클릭 시 하네스를 재부팅하지 않고 라우팅 모델 매핑을 즉시 업데이트.
4. **버전 이력 관리 및 원클릭 롤백 (Version Snapshot & Rollback)**: 덮어쓰지 않고 `latest`, `v1.1.0`, `v1.0.0` 등 버전 이력을 저장하여 언제든지 과거 안정된 모델 매핑 버전으로 복원 가능.

---

## 2. 모듈 아키텍처 (Architecture & Flow)

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Kibana Usage Dashboard (HTML/JS)                      │
│                                                                        │
│ * Header Notification Badge: "💡 신규 저비용 모델(gpt-5.6-luna-v2) 발견!"  │
│ * Version Select Control: [ Latest (v1.2.0) ▼ ]                        │
│ * Model & Price Comparison Modal (이전 버전 vs 신규 버전 단가/성능 비교표)   │
│ * Action Buttons: [ 🩹 Apply Healing Update ]  [ ⏪ Rollback Version ] │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ HTTP POST /v1/models/heal
                                   │ HTTP POST /v1/models/version/switch
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 LLM Routing Harness Proxy (Port 18080)                 │
│                                                                        │
│ * ModelRegistry (`src/tierbridge/model_registry.py`)                   │
│   - Persistent Config: `config/model_versions.json`                    │
│   - Active Version Pointer: "latest" -> "v1.2.0"                       │
│   - History Snapshots: v1.0.0, v1.1.0, v1.2.0                          │
│ * Dynamic Router (`src/tierbridge/router.py`)                          │
│   - Reads active model mapping from ModelRegistry in real-time         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2.1 실제 업스트림 모델 동적 감지 및 핫패치 생성 (Live Upstream Dynamic Discovery)

정적 템플릿에 의존하지 않고, 실제 OpenAI 업스트림 백엔드 API를 동적으로 조회하여 신규 모델 릴리즈를 실시간 탐지하고 최적 매핑을 제안합니다:
- **업스트림 모델 조회 엔드포인트**:
  - `GET https://chatgpt.com/backend-api/codex/models?client_version=1.0.0`
  - 인증: `~/.codex/auth.json`의 Bearer Token 및 `chatgpt-account-id`
- **신규 모델 감지 정책 (Detection Logic)**:
  - 업스트림 카탈로그의 모델 목록(slug, display_name, description 등)을 조회 (TTL 캐시 60초 적용).
  - 현재 활성 버전(`active_mapping`)의 모델 라인업과 업스트림 가용 모델을 비교:
    - 현재 매핑이 `gpt-5.6` 계열인데 업스트림에 `gpt-6` 계열(`gpt-6-luna`, `gpt-6-sol` 등)이 감지되면 즉시 `has_new_healing: true` 트리거.
    - 업스트림에 차세대 `gpt-6.1` 계열(`gpt-6.1-sol` 등)이 출시 감지될 경우 최신 핫패치(`v2.1.0-gpt61-hotpatch`) 제안 트리거.
    - 구형 버전(`v0.9.0-test-legacy`, `gpt-5.4-mini`, `gpt-5.5` 등)인 경우에도 상위 모델 감지로 즉시 트리거.
    - 이미 최신 업스트림 모델로 핫패치가 완료된 상태(예: `v2.0.0-gpt6-hotpatch`, `v2.1.0-gpt61-hotpatch`)일 경우 `has_new_healing: false`로 자동 은닉.
- **동적 핫패치 매핑 생성 규칙 (Dynamic Recommendation Rule)**:
  - `BRONZE` / `SILVER` (경량/고효율 티어): 업스트림의 경량 고속 모델 (예: `gpt-6-luna`, in: $0.10, out: $0.50)
  - `GOLD` / `PLATINUM` / `DIAMOND` / `CHALLENGER` (고성능/엔지니어링 티어): 업스트림의 최신 코딩 모델 (`gpt-6.1-sol` 우선 탑재, 미지원 시 `gpt-6-sol`, in: $2.00, out: $10.00)
- **원클릭 핫패칭 릴리즈 적용 (`POST /v1/models/heal`)**:
  - 탐지된 업스트림 모델을 기반으로 신규 버전 스냅샷(예: `v2.0.0-gpt6-hotpatch`)을 동적 생성하고 즉시 활성화.
  - 적용 완료 시 대시보드 알림 배너 자동 닫힘 및 하단 타임라인 이력 기록.

- **원클릭 핫패칭 릴리즈 적용 및 배포 영구 보존 (Dual-Sink Persistence & Deployment Preservation)**:
  - `ModelRegistry.get_config_path()`는 라이브 런타임의 설정 파일(`~/.tierbridge/live/config/model_versions.json`)을 1순위로 탐색하여 참조합니다.
  - 사용자가 핫패칭을 적용하거나 드롭다운으로 변경한 `active_version` 런타임 상태는 `deploy.sh` 동기화 시 `--exclude='config/model_versions.json'` 규칙과 라이브 경로 1순위 참조 정책에 의해, **배포(`deploy.sh`)를 몇 번 가동하더라도 활성화된 모델 버전(Active Version) 상태가 리셋되지 않고 100% 지속 유지**됩니다.
  - 핫패치가 완료되면 `has_new_healing`은 `false`로 닫히고, 대시보드 버전 선택 드롭다운과 하단 타임라인에 `v2.0.0-gpt6-hotpatch`가 이력으로 남게 됩니다.

- **단가 절감율 표출 규격 (Dynamic `savings_pct`)**:
  - `savings_pct > 0`: `+33.3% (절감)` (초록색 에메랄드 볼드)
  - `savings_pct < 0`: `-220.0% (인상)` (빨간색 로즈 볼드)
  - `savings_pct == 0`: `0.0% (동일)` (슬레이트 세미볼드)

---

## 2.2 핫패치 이력 로그 파싱 & 대시보드 타임라인 (Hot-patch History & Timeline)

핫패칭 적용 및 버전 전환 실행 시 `harness.log`에 구조화된 이벤트를 남기며 대시보드에 실시간 기록됩니다:
1. **이벤트 로그 규격**:
   - `➔ [HEALING] Hot-patch applied | new_version_id=v1.1.0-sample-demo | message=...`
   - `➔ [VERSION_SWITCH] Switched model version | version_id=v1.0.0 | active_version_id=v1.0.0`
2. **대시보드 시각화 (Kibana Real-time Timeline)**:
   - `usage_dashboard.html` 하단에 **`🩹 모델 핫패치 & 버전 전환 이력 (Recent Hot-Patch & Version History)`** 타임라인 표를 배치하여 실시간 이력을 표출합니다.

---

## 2.3 주기적 공식 단가 동기화 시스템 (Periodic Official Pricing Sync System)

OpenAI 공식 가격표 변동 및 신규 모델 단가를 자동으로 수집·반영하기 위한 동적 크롤링 및 동기화 엔진입니다:
- **공식 단가 데이터 소스**:
  - `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` (OpenAI Developer Pricing 공식 피드 실시간 연동)
- **로컬 영구 캐시 및 듀얼 싱크 저장소 (`config/official_prices.json`)**:
  - 수집된 공식 단가(Input / Output 토큰당 단가, 1M 기준 변환값)를 로컬 설정에 영구 저장.
  - 네트워크 단절 및 오프라인 시에도 마지막으로 동기화된 최신 공식 단가를 즉시 참조하는 Fallback 구조.
- **주기적 백그라운드 갱신 루프**:
  - 하네스 프록시 기동 시 1차 즉시 동기화 수행.
  - 6시간 주기 백그라운드 비동기 태스크(`run_periodic_pricing_sync`)로 최신 단가 자동 확인 및 갱신.
- **HealingEngine 자동 연동**:
  - 신규 모델 핫패치 추천(`get_dynamic_recommendation`) 및 비교표 산출 시 `OfficialPricingCrawler.get_price(model)`를 호출하여, 하드코딩 추정치 대신 실제 공식 단가(예: `gpt-6-luna`: $0.10 / $0.50, `gpt-6-sol`: $2.00 / $10.00)를 100% 동적 주입.

---

## 3. 버전 관리 규격 (`config/model_versions.json`)

```json
{
  "active_version": "v1.0.0",
  "latest_version_id": "v1.0.0",
  "versions": {
    "v1.0.0": {
      "version_id": "v1.0.0",
      "name": "Standard Baseline v1.0.0 (GPT-5.6 Lineup)",
      "updated_at": "2026-07-31T00:00:00",
      "description": "초기 기본 표준 모델 게이밍 랭크 스냅샷",
      "mapping": {
        "BRONZE": {"model": "gpt-5.6-luna", "effort": "low", "input_price": 1.0, "output_price": 3.0},
        "SILVER": {"model": "gpt-5.6-luna", "effort": "medium", "input_price": 1.0, "output_price": 3.0},
        "GOLD": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.5, "output_price": 10.0},
        "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
        "DIAMOND": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
        "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 5.0, "output_price": 20.0}
      }
    },
    "v1.1.0-healing-hotpatch": {
      "version_id": "v1.1.0-healing-hotpatch",
      "name": "Healing Hotpatch Release v1.1.0",
      "updated_at": "2026-08-14T14:00:00",
      "description": "신규 저비용/고출력 모델 핫패치 릴리즈 스냅샷",
      "mapping": {
        "BRONZE": {"model": "gpt-5.6-luna", "effort": "low", "input_price": 1.0, "output_price": 3.0},
        "SILVER": {"model": "gpt-5.6-luna", "effort": "medium", "input_price": 1.0, "output_price": 3.0},
        "GOLD": {"model": "gpt-5.6-terra", "effort": "medium", "input_price": 2.5, "output_price": 10.0},
        "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
        "DIAMOND": {"model": "gpt-5.6-terra", "effort": "high", "input_price": 2.5, "output_price": 10.0},
        "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh", "input_price": 5.0, "output_price": 20.0}
      }
    }
  }
}
```

---

## 4. REST API 명세 (Harness Endpoints)

1. `GET /v1/models/healing-status`:
   - 현재 활성화된 모델 버전, 신규 업데이트 가능 버전 및 단가 비교표 반환.
2. `POST /v1/models/heal`:
   - 탐지된 신규 모델 매핑으로 핫패치 업데이트 수행 및 신규 버전(`v1.1.0-healing-hotpatch`) 스냅샷 생성.
3. `POST /v1/models/version/switch`:
   - 지정한 과거 버전 ID(e.g., `v1.0.0`, `latest`)로 라우터 매핑 즉시 롤백/복원.
4. `GET /v1/dashboard/stats`:
   - 3초 주기 대시보드 라이브 오토싱크(Live Auto-Sync)용 토큰/비용/크레딧 통계, 월/세션 옵션 및 힐링 이력 반환.
5. `POST /v1/models/pricing/sync`:
   - OpenAI 공식 가격 피드를 즉시 크롤링하여 `config/official_prices.json`에 동기화하고 최신 단가표 반환.
