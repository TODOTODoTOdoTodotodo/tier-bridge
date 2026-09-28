# Workspace Shared Credits Pool Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
ChatGPT Business 및 Enterprise 조직 계정에서는 사용자 개인별 월간 지출 한도(`spend_control.individual_limit`)와 별개로, 조직 전체가 공유하는 **워크스페이스 공용 크레딧 풀(Workspace Shared Credits Pool)**이 존재합니다.

개인 잔여 한도가 남아있더라도(예: 3,000 Cr 중 2,537 Cr 잔여) 회사의 공용 풀이 소진되면(`workspace_member_credits_depleted`, `credits.balance: 0`) OpenAI 백엔드가 모든 모델 요청에 대해 즉각 `429 Too Many Requests (usage_limit_reached)`를 반환하게 됩니다.

본 사양서는 이러한 공용 풀의 실시간 잔여량 및 고갈 상태를 백엔드 API에서 가로채 대시보드(Enterprise Balance Widget)와 CLI(`tierbridge-credit` / `--balance`)에 실시간 시각화하여, 원인 규명 및 관리자 충전 요청을 즉시 파악할 수 있도록 관측성(Observability)을 고도화하는 규격을 정의합니다.

---

## 2. 데이터 수집 및 파싱 규격 (`src/tierbridge/credit_interceptor.py`)

### 2.1 OpenAI 엔터프라이즈 백엔드 API 스키마 매핑
`GET https://chatgpt.com/backend-api/codex/usage` 응답에서 아래 필드를 추출:
```json
{
  "credits": {
    "has_credits": false,
    "balance": "0",
    "unlimited": false,
    "overage_limit_reached": true
  },
  "rate_limit_reached_type": {
    "type": "workspace_member_credits_depleted"
  },
  "rate_limit_upsell": {
    "title": "You've reached your workspace credit limit",
    "description": "Your workspace is out of credits. Ask your workspace owner to add more."
  }
}
```

### 2.2 인터셉터 반환 모델 (`fetch_enterprise_usage`)
기존 개인 한도 정보에 `workspace_pool` 딕셔너리를 추가:
```python
{
    # 개인 한도 정보 (Individual Spend Control)
    "limit": limit_val,
    "used": used_val,
    "remaining": rem_val,
    "used_percent": round(used_pct, 1),
    "remaining_percent": round(rem_pct, 1),
    "reset_at": reset_at_val,

    # 워크스페이스 공용 풀 정보 (Workspace Shared Pool)
    "workspace_pool": {
        "has_credits": bool(credits_obj.get("has_credits", True)),
        "balance": float(credits_obj.get("balance", 0)),
        "is_depleted": is_depleted,  # balance <= 0 or overage_limit_reached or type == "workspace_member_credits_depleted"
        "status": "DEPLETED" if is_depleted else "ACTIVE",
        "title": upsell.get("title", ""),
        "description": upsell.get("description", "")
    }
}
```

---

## 3. UI 및 CLI 표현 규격

### 3.1 웹 대시보드 (`usage_dashboard.html`, `analyze_usage.py`)
1. **Enterprise Balance Widget 상단 상태 뱃지**:
   - `[Business]` 플랜 뱃지 우측에 **[🏢 워크스페이스 풀: 정상]** 또는 **[⚠️ 워크스페이스 풀: 고갈 (0 Cr)]** 뱃지 표출.
   - **정상 (ACTIVE)**: `bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30`
   - **고갈 (DEPLETED)**: `bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30 animate-pulse`
2. **경고 배너 (Depleted Warning Banner)**:
   - 공용 풀 고갈 시 위젯 하단 또는 내부에 알림 배너 렌더링:
     *"⚠️ 사내 워크스페이스 공유 크레딧이 소진되어 프롬프트 요청이 일시 대기 중입니다. 관리자(Owner)에게 충전을 요청하세요."*
3. **실시간 오토싱크 (Live Sync)**:
   - 3초 주기 대시보드 폴링(`/v1/dashboard/stats`) 시 `workspace_pool` 상태를 동적으로 DOM에 반영.

### 3.2 CLI 터미널 출력 (`analyze_usage.py --balance` / `tierbridge-credit`)
```
=====================================================================================
💳 [ChatGPT Enterprise] 실시간 계정 잔여 크레딧 및 지출 한도 조회
=====================================================================================
👤 사용자 계정      : user@company.com (Plan: business)
🏢 계정 ID         : 00000000-0000-0000-0000-000000000000
-------------------------------------------------------------------------------------
🏢 워크스페이스 공용 크레딧 풀 (Workspace Shared Credits):
  • 풀 상태 (Status)         : ⚠️ 고갈 (DEPLETED / 잔여 0.00 Cr)
  • 초과 한도 도달 여부       : True (overage_limit_reached)
  • 조치 가이드              : "Your workspace is out of credits. Ask your workspace owner to add more."
-------------------------------------------------------------------------------------
📊 개인 크레딧 한도 및 소모 현황 (Monthly Spend Control):
  • 월간 할당 한도 (Limit)     : 3,000.00 Credits
  • 실제 누적 소모량 (Used)    : 462.04 Credits (15.4%)
  • 실제 잔여 크레딧 (Remaining): 2,537.96 Credits (84.6%)
  • 크레딧 리셋 일시 (Reset)   : 2026-10-01 09:00:01
=====================================================================================
```
