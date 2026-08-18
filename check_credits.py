#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
from datetime import datetime

def main():
    auth_path = os.path.expanduser("~/.codex/auth.json")
    if not os.path.exists(auth_path):
        print(f"❌ [오류] 인증 설정 파일({auth_path})을 찾을 수 없습니다.")
        sys.exit(1)
        
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth = json.load(f)
            
        tokens = auth.get("tokens", {})
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        
        req = urllib.request.Request("https://chatgpt.com/backend-api/codex/usage")
        req.add_header("Authorization", f"Bearer {access_token}")
        if account_id:
            req.add_header("chatgpt-account-id", account_id)
        req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        email = data.get("email", "N/A")
        plan = data.get("plan_type", "business")
        spend = data.get("spend_control", {}).get("individual_limit", {})
        limit = float(spend.get("limit", 0))
        used = float(spend.get("used", 0))
        remaining = float(spend.get("remaining", 0))
        used_pct = spend.get("used_percent", 0)
        rem_pct = spend.get("remaining_percent", 100)
        reset_at = spend.get("reset_at")
        reset_str = datetime.fromtimestamp(reset_at).strftime("%Y-%m-%d %H:%M:%S") if reset_at else "N/A"
        
        print("=" * 85)
        print("💳 [ChatGPT Enterprise] 실시간 계정 잔여 크레딧 및 지출 한도 조회")
        print("=" * 85)
        print(f"👤 사용자 계정      : {email} (Plan: {plan})")
        print(f"🏢 계정 ID         : {account_id}")
        print("-" * 85)
        print("📊 크레딧 한도 및 소모 현황 (Monthly Spend Control):")
        print(f"  • 월간 할당 한도 (Limit)     : {limit:,.2f} Credits")
        print(f"  • 실제 누적 소모량 (Used)    : {used:,.2f} Credits ({used_pct}%)")
        print(f"  • 실제 잔여 크레딧 (Remaining): {remaining:,.2f} Credits ({rem_pct}%)")
        print(f"  • 크레딧 리셋 일시 (Reset)   : {reset_str}")
        print("=" * 85)
    except Exception as e:
        print(f"❌ [오류] 엔터프라이즈 실시간 크레딧 조회 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
