import os
import json
import asyncio
import httpx
from datetime import datetime
from typing import Optional, Dict, Any

class CreditInterceptor:
    """
    OpenAI ChatGPT Enterprise 백엔드의 실제 차감 크레딧(Delta)을 
    비동기 백그라운드로 추적하여 오차 0%로 동기화하는 인터셉터
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CreditInterceptor, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.last_known_used: Optional[float] = None
        self.last_known_remaining: Optional[float] = None
        self.spend_limit: Optional[float] = None
        self.reset_at: Optional[int] = None
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=8.0)
        return self._client

    async def fetch_enterprise_usage(self, auth_token: Optional[str] = None, account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        ChatGPT Enterprise 백엔드 API에서 실시간 지출 한도 및 소모량 조회
        """
        if not auth_token:
            auth_path = os.path.expanduser("~/.codex/auth.json")
            if os.path.exists(auth_path):
                try:
                    with open(auth_path, "r", encoding="utf-8") as f:
                        auth_data = json.load(f)
                    tokens = auth_data.get("tokens", {})
                    auth_token = f"Bearer {tokens.get("access_token", "")}"
                    account_id = tokens.get("account_id")
                except Exception:
                    pass

        if not auth_token:
            return None

        headers = {
            "Authorization": auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        try:
            client = self.get_client()
            response = await client.get("https://chatgpt.com/backend-api/codex/usage", headers=headers)
            if response.status_code == 200:
                data = response.json()
                spend = data.get("spend_control", {}).get("individual_limit", {})
                return {
                    "limit": float(spend.get("limit", 0)),
                    "used": float(spend.get("used", 0)),
                    "remaining": float(spend.get("remaining", 0)),
                    "used_percent": spend.get("used_percent", 0),
                    "remaining_percent": spend.get("remaining_percent", 100),
                    "reset_at": spend.get("reset_at")
                }
        except Exception:
            pass
        return None

    async def track_turn_delta(
        self,
        session_id: Optional[str],
        decision: str,
        model: str,
        in_tok: int,
        out_tok: int,
        loc: int,
        est_cost: float,
        auth_token: Optional[str] = None,
        account_id: Optional[str] = None,
        now_str: Optional[str] = None
    ):
        """
        비동기 백그라운드 코루틴으로 호출되어 백엔드 과금 집계 유예(1.0s) 후
        실제 차감 델타 크레딧을 산출하여 로그에 기록
        """
        if now_str is None:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid_tag = f" [sid: {session_id}]" if session_id else ""

        # 백엔드 과금 전파 딜레이(Eventual Consistency) 대응 유예
        await asyncio.sleep(1.0)

        async with self._lock:
            usage_data = await self.fetch_enterprise_usage(auth_token, account_id)
            if usage_data and "used" in usage_data:
                curr_used = usage_data["used"]
                curr_remaining = usage_data["remaining"]
                self.spend_limit = usage_data["limit"]
                self.reset_at = usage_data["reset_at"]

                if self.last_known_used is not None:
                    delta_credit = max(0.0, round(curr_used - self.last_known_used, 4))
                else:
                    # 최초 턴 초기화 시점: 로컬 추정 크레딧으로 안전 대입
                    delta_credit = round(est_cost / 0.20, 4)

                self.last_known_used = curr_used
                self.last_known_remaining = curr_remaining

                # 실제 크레딧 델타 및 실시간 잔여량 태그를 포함한 USAGE 로그 출력
                print(
                    f"[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | "
                    f"input={in_tok} output={out_tok} tokens | "
                    f"real_credit={delta_credit:.4f} | balance={curr_remaining:.2f} | "
                    f"loc={loc} lines | cost=${est_cost:.6f} USD",
                    flush=True
                )
                return

        # 백엔드 조회 실패 시 안전 폴백(Fallback) 로깅
        est_credits = est_cost / 0.20
        print(
            f"[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | "
            f"input={in_tok} output={out_tok} tokens | "
            f"loc={loc} lines | cost=${est_cost:.6f} USD",
            flush=True
        )

interceptor = CreditInterceptor()
