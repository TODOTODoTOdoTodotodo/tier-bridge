#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
from datetime import datetime

def check_credits():
    auth_path = os.path.expanduser("~/.codex/auth.json")
    if not os.path.exists(auth_path):
        print(f"❌ [오류] Codex 인증 설정 파일({auth_path})을 찾을 수 없습니다.")
        sys.exit(1)

    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth_data = json.load(f)
        
        tokens = auth_data.get("tokens", {})
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")

        if not access_token:
            print("❌ [오류] auth.json에 유효한 access_token이 없습니다.")
            sys.exit(1)

        req = urllib.request.Request("https://chatgpt.com/backend-api/codex/usage")
        req.add_header("Authorization", f"Bearer {access_token}")
        if account_id:
            req.add_header("chatgpt-account-id", account_id)
        req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                print(f"❌ [오류] API 응답 에러: HTTP {response.status}")
                sys.exit(1)
            raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)

        email = data.get("email", "N/A")
        plan_type = data.get("plan_type", "N/A")
        spend_control = data.get("spend_control", {})
        indiv = spend_control.get("individual_limit", {})
        
        limit = float(indiv.get("limit", 0))
        used = float(indiv.get("used", 0))
        remaining = float(indiv.get("remaining", 0))
        # 관리자(Admin)가 유동적으로 조정한 월간 한도를 기준으로 실시간 동적 계산
        used_percent = (used / limit * 100.0) if limit > 0 else 0.0
        remaining_percent = max(0.0, 100.0 - used_percent) if limit > 0 else 100.0
        reset_at = indiv.get("reset_at")
        
        reset_dt_str = "N/A"
        if reset_at:
            reset_dt_str = datetime.fromtimestamp(reset_at).strftime("%Y-%m-%d %H:%M:%S")

        print("=" * 85)
        print("💳 [ChatGPT Enterprise] 실시간 계정 잔여 크레딧 및 지출 한도 조회")
        print("=" * 85)
        print(f"👤 사용자 계정      : {email} (Plan: {plan_type})")
        print(f"🏢 계정 ID         : {account_id}")
        print("-" * 85)
        print("📊 크레딧 한도 및 소모 현황 (Monthly Spend Control):")
        print(f"  • 월간 할당 한도 (Limit)     : {limit:,.2f} Credits")
        print(f"  • 실제 누적 소모량 (Used)    : {used:,.2f} Credits ({used_percent:.1f}%)")
        print(f"  • 실제 잔여 크레딧 (Remaining): {remaining:,.2f} Credits ({remaining_percent:.1f}%)")
        print(f"  • 크레딧 리셋 일시 (Reset)   : {reset_dt_str}")
        print("=" * 85)

    except Exception as e:
        print(f"❌ [오류] 크레딧 조회 중 예외가 발생했습니다: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_credits()
