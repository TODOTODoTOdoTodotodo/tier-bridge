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

## 2.1 모델 스냅샷 버전 테스트 (Legacy Test Snapshot Scenario)

힐링 핫패치 감지 및 무중단 원클릭 핫패칭/롤백 테스트를 위해 구형/테스트 스냅샷 버전을 지원합니다:
- **`v0.9.0-test-legacy` (테스트 스냅샷)**:
  - `LUNA` 등급 매핑: `gpt-5.4-mini` (in: $0.15, out: $0.60)
  - `TERRA` & `SOL` 등급 매핑: `gpt-5.5` (in: $3.00, out: $12.00)
- **`v1.0.0` (Baseline 표준 스냅샷 백업본)**:
  - `LUNA` 등급 매핑: `gpt-5.6-luna` (in: $1.00, out: $3.00)
  - `TERRA` 등급 매핑: `gpt-5.6-terra` (in: $2.50, out: $10.00)
  - `SOL` 등급 매핑: `gpt-5.6-sol` (in: $5.00, out: $20.00)

`v0.9.0-test-legacy` 스냅샷이 활성화되면 `HealingEngine`이 최신 `gpt-5.6` 라인업과의 단가/성능 차이를 자동 감지하여 `has_new_healing: true` 알림 배너를 트리거합니다.

---

## 3. 버전 관리 규격 (`config/model_versions.json`)

```json
{
  "active_version": "v1.1.0",
  "versions": {
    "v1.0.0": {
      "name": "Standard 3-Tier v1.0",
      "updated_at": "2026-07-31T00:00:00",
      "mapping": {
        "LUNA:LOW": {"model": "gpt-5.6-luna", "effort": "low"},
        "LUNA:MEDIUM": {"model": "gpt-5.6-luna", "effort": "medium"},
        "TERRA:MEDIUM": {"model": "gpt-5.6-terra", "effort": "medium"},
        "TERRA:HIGH": {"model": "gpt-5.6-terra", "effort": "high"},
        "SOL:EXTRA_HIGH": {"model": "gpt-5.6-sol", "effort": "xhigh"}
      }
    },
    "v1.1.0": {
      "name": "Healing Update: LUNA-v2 Cost Reduction",
      "updated_at": "2026-08-13T14:00:00",
      "mapping": {
        "LUNA:LOW": {"model": "gpt-5.6-luna-v2", "effort": "low"},
        "LUNA:MEDIUM": {"model": "gpt-5.6-luna-v2", "effort": "medium"},
        "TERRA:MEDIUM": {"model": "gpt-5.6-terra", "effort": "medium"},
        "TERRA:HIGH": {"model": "gpt-5.6-terra", "effort": "high"},
        "SOL:EXTRA_HIGH": {"model": "gpt-5.6-sol", "effort": "xhigh"}
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
   - 탐지된 신규 모델 매핑으로 핫패치 업데이트 수행 및 신규 버전 스냅샷 생성.
3. `POST /v1/models/version/switch`:
   - 지정한 과거 버전 ID(e.g., `v1.0.0`)로 라우터 매핑 즉시 롤백/복원.
