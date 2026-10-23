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
        self.session_usage: Dict[str, Dict[str, Any]] = {}

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
                limit_val = float(spend.get("limit", 0))
                used_val = float(spend.get("used", 0))
                rem_val = float(spend.get("remaining", 0))
                # 관리자(Admin)가 조정한 유동적 limit을 기준으로 실시간 비율 산출
                used_pct = (used_val / limit_val * 100.0) if limit_val > 0 else 0.0
                rem_pct = max(0.0, 100.0 - used_pct) if limit_val > 0 else 100.0

                # 워크스페이스 공용 풀 정보 추출
                credits_obj = data.get("credits", {})
                pool_balance = float(credits_obj.get("balance", 0)) if credits_obj.get("balance") is not None else 0.0
                has_credits = bool(credits_obj.get("has_credits", True))
                overage_limit_reached = bool(credits_obj.get("overage_limit_reached", False))
                rl_type = (data.get("rate_limit_reached_type") or {}).get("type", "")
                is_depleted = (not has_credits) or (pool_balance <= 0) or overage_limit_reached or (rl_type == "workspace_member_credits_depleted")
                upsell = data.get("rate_limit_upsell") or {}

                return {
                    "limit": limit_val,
                    "used": used_val,
                    "remaining": rem_val,
                    "used_percent": round(used_pct, 1),
                    "remaining_percent": round(rem_pct, 1),
                    "reset_at": spend.get("reset_at"),
                    "workspace_pool": {
                        "has_credits": has_credits,
                        "balance": pool_balance,
                        "is_depleted": is_depleted,
                        "status": "DEPLETED" if is_depleted else "ACTIVE",
                        "rate_limit_type": rl_type,
                        "title": upsell.get("title", ""),
                        "description": upsell.get("description", "")
                    }
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

                # 세션별 누적 소모량 인메모리 갱신
                if session_id:
                    if session_id not in self.session_usage:
                        self.session_usage[session_id] = {
                            "session_id": session_id,
                            "turns": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                            "real_credits": 0.0,
                            "loc": 0
                        }
                    e = self.session_usage[session_id]
                    e["turns"] += 1
                    e["input_tokens"] += in_tok
                    e["output_tokens"] += out_tok
                    e["total_tokens"] += (in_tok + out_tok)
                    e["real_credits"] = round(e["real_credits"] + delta_credit, 4)
                    e["loc"] += loc

                # 실제 크레딧 델타 및 실시간 잔여량 태그를 포함한 불변 물리량 USAGE 로그 출력 (가변적 USD 생략)
                print(
                    f"[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | "
                    f"input={in_tok} output={out_tok} tokens | "
                    f"real_credit={delta_credit:.4f} | balance={curr_remaining:.2f} | "
                    f"loc={loc} lines",
                    flush=True
                )
                return

        # 백엔드 조회 실패 시 안전 폴백(Fallback) 로깅
        fallback_credit = round(est_cost / 0.20, 4)
        if session_id:
            if session_id not in self.session_usage:
                self.session_usage[session_id] = {
                    "session_id": session_id,
                    "turns": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "real_credits": 0.0,
                    "loc": 0
                }
            e = self.session_usage[session_id]
            e["turns"] += 1
            e["input_tokens"] += in_tok
            e["output_tokens"] += out_tok
            e["total_tokens"] += (in_tok + out_tok)
            e["real_credits"] = round(e["real_credits"] + fallback_credit, 4)
            e["loc"] += loc

        print(
            f"[{now_str}]{sid_tag} ➔ [USAGE: {decision}] ({model}) | "
            f"input={in_tok} output={out_tok} tokens | "
            f"loc={loc} lines",
            flush=True
        )

    def get_session_usage(self, session_id: str, since_timestamp: Optional[str] = None) -> Dict[str, Any]:
        """
        특정 session_id에 대해 인메모리 추적된 사용량을 반환하며,
        인메모리 기록이 없거나 0인 경우 harness.log에서 실제 차감 크레딧을 스캔하여 반환 (하이브리드 캐시)
        """
        if session_id in self.session_usage and self.session_usage[session_id].get("real_credits", 0) > 0:
            return dict(self.session_usage[session_id])

        return self._scan_log_for_session_usage(session_id, since_timestamp=since_timestamp)

    def _scan_log_for_session_usage(self, session_id: str, since_timestamp: Optional[str] = None) -> Dict[str, Any]:
        import re
        usage_pat = re.compile(
            r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*\[sid:\s*(?P<sid>[^\]]+)\]\s*➔ \[USAGE[^\]]*\]\s*\((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| real_credit=(?P<real_credit>[\d\.]+))?(?: \| balance=(?P<balance>[\d\.]+))?(?: \| loc=(?P<loc>\d+) lines)?"
        )
        candidates = [
            os.path.expanduser("~/.harnex/live/harness.log"),
            os.path.expanduser("~/.tierbridge/live/harness.log"),
            "harness.log"
        ]
        log_file = None
        for p in candidates:
            if os.path.exists(p):
                log_file = p
                break

        empty_res = {"session_id": session_id, "turns": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "real_credits": 0.0, "loc": 0}
        if not log_file:
            return empty_res

        since_str = ""
        if since_timestamp:
            try:
                dt = datetime.fromisoformat(since_timestamp)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                since_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                since_str = str(since_timestamp)[:19].replace("T", " ")

        turns = 0
        in_tok = 0
        out_tok = 0
        credits = 0.0
        loc = 0

        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = usage_pat.search(line)
                    if not m:
                        continue
                    sid = m.group("sid")
                    if sid != session_id:
                        continue
                    ts = m.group("timestamp")
                    if since_str and ts and ts < since_str:
                        continue
                    turns += 1
                    in_tok += int(m.group("in_tok"))
                    out_tok += int(m.group("out_tok"))
                    cr_str = m.group("real_credit")
                    if cr_str:
                        credits += float(cr_str)
                    loc_str = m.group("loc")
                    if loc_str:
                        loc += int(loc_str)
        except Exception:
            pass

        result = {
            "session_id": session_id,
            "turns": turns,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
            "real_credits": round(credits, 4),
            "loc": loc
        }
        if turns > 0:
            self.session_usage[session_id] = dict(result)
        return result

interceptor = CreditInterceptor()
