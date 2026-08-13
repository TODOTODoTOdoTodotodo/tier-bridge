# 🩹 Model Healing Factor & Dynamic Version Management

이 문서는 TierBridge 하네스에 신규 모델 및 단가 인하 버전이 등장했을 때, 이를 대시보드에서 시각적으로 감지하고 원클릭 핫패치(Hot-patch) 및 롤백(Rollback) 버전 관리 기능을 제공하는 **`Model Healing Factor System`**의 명세 문서입니다.

---

## 1. 개요 및 목적 (Background & Objectives)

LLM 모델 라인업(OpenAI/ChatGPT Enterprise 등)은 빠른 주기로 신규 모델(e.g., `gpt-5.7`, `gpt-5.6-luna-v2`)이 추가되거나 입력/출력 토큰 단가 인하 패치가 이루어집니다.

`Model Healing Factor System`은 다음을 목적으로 설계되었습니다:
1. **신규 모델 및 비용 절감 찬스 자동 감지**: 최신 모델 라인업 정보 및 비용 단가를 대시보드에서 즉시 탐지 및 비교.
2. **원클릭 하네스 모델 교체 (Healing Hot-patch)**: 사용자가 대시보드 상에서 버튼 클릭 시 하네스를 재부팅하지 않고 라우팅 모델 매핑을 즉시 업데이트.
3. **버전 이력 관리 및 원클릭 롤백 (Version Snapshot & Rollback)**: 덮어쓰지 않고 `latest`, `v1.1.0`, `v1.0.0` 등 버전 이력을 저장하여 언제든지 과거 안정된 모델 매핑 버전으로 복원 가능.

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
