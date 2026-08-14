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

힐링 핫패치 감지 및 무중단 원클릭 핫패칭/롤백 테스트를 위해 구형/테스트 스냅샷 버전을 지원하며, 기존 모델명 대신 단일화된 게이밍 랭크 티어(`BRONZE`, `SILVER`, `GOLD`, `PLATINUM`, `DIAMOND`, `CHALLENGER`) 매핑을 사용합니다:
- **`v1.0.0` (Baseline 표준 Active 스냅샷 - 기본값)**:
  - `BRONZE` / `SILVER` 등급 매핑: `gpt-5.6-luna` (in: $1.00, out: $3.00)
  - `GOLD` / `PLATINUM` / `DIAMOND` 등급 매핑: `gpt-5.6-terra` (in: $2.50, out: $10.00)
  - `CHALLENGER` 등급 매핑: `gpt-5.6-sol` (in: $5.00, out: $20.00)
- **`v0.9.0-test-legacy` (테스트 롤백 스냅샷)**:
  - `BRONZE` / `SILVER` 등급 매핑: `gpt-5.4-mini` (in: $0.15, out: $0.60)
  - `GOLD` ~ `CHALLENGER` 등급 매핑: `gpt-5.5` (in: $3.00, out: $12.00)

기본 배포 및 런타임 활성 버전(`active_version`)은 최신 표준 모델 스냅샷인 **`v1.0.0`**으로 유지되며, 사용자가 핫패치 검증을 위해 `v0.9.0-test-legacy` 스냅샷으로 전환했을 때만 `HealingEngine`이 `has_new_healing: true` 알림 배너를 트리거합니다.

- **원클릭 핫패칭 릴리즈 적용 및 배포 영구 보존 (Dual-Sink Persistence & Deployment Preservation)**:
  - `ModelRegistry.get_config_path()`는 라이브 런타임의 설정 파일(`~/.tierbridge/live/config/model_versions.json`)을 1순위로 탐색하여 참조합니다.
  - 사용자가 핫패칭을 적용하거나 드롭다운으로 변경한 `active_version` 런타임 상태는 `deploy.sh` 동기화 시 `--exclude='config/model_versions.json'` 규칙과 라이브 경로 1순위 참조 정책에 의해, **배포(`deploy.sh`)를 몇 번 가동하더라도 활성화된 모델 버전(Active Version) 상태가 리셋되지 않고 100% 지속 유지**됩니다.
  - 핫패치가 완료되면 `has_new_healing`은 `false`로 닫히고, 대시보드 버전 선택 드롭다운과 하단 타임라인에 `v1.1.0-healing-hotpatch`가 이력으로 남게 됩니다.

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

## 3. 버전 관리 규격 (`config/model_versions.json`)

```json
{
  "active_version": "v1.1.0",
  "versions": {
    "v1.0.0": {
      "name": "Standard 3-Tier v1.0",
      "updated_at": "2026-07-31T00:00:00",
      "mapping": {
        "BRONZE": {"model": "gpt-5.6-luna", "effort": "low"},
        "SILVER": {"model": "gpt-5.6-luna", "effort": "medium"},
        "GOLD": {"model": "gpt-5.6-terra", "effort": "medium"},
        "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high"},
        "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh"}
      }
    },
    "v1.1.0": {
      "name": "Healing Update: LUNA-v2 Cost Reduction",
      "updated_at": "2026-08-13T14:00:00",
      "mapping": {
        "BRONZE": {"model": "gpt-5.6-luna-v2", "effort": "low"},
        "SILVER": {"model": "gpt-5.6-luna-v2", "effort": "medium"},
        "GOLD": {"model": "gpt-5.6-terra", "effort": "medium"},
        "PLATINUM": {"model": "gpt-5.6-terra", "effort": "high"},
        "CHALLENGER": {"model": "gpt-5.6-sol", "effort": "xhigh"}
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
