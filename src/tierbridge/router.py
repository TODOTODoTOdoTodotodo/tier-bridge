import os
import json
import httpx
from typing import Tuple
from tierbridge.models import UnifiedRequest

class Router:
    _client = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None:
            # 신속한 대처(Fail-fast)를 위해 타임아웃을 8.0초로 타이트하게 조율
            cls._client = httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            )
        return cls._client
    @staticmethod
    def extract_user_prompt_and_turn_status(unified_request: UnifiedRequest) -> Tuple[str, bool, str]:
        """
        가장 최근의 사용자 질의, 신규 유저 턴 여부, 및 서브 스텝 작업 텍스트를 추출합니다.
        Returns: (user_prompt, is_new_user_turn, substep_prompt)
        """
        if not unified_request.messages:
            return "", False, ""

        # 가장 최근 메시지가 유저 역할이고 내용이 있는 경우 신규 유저 입력 턴으로 판단
        last_msg = unified_request.messages[-1]
        is_new_user_turn = (last_msg.role == "user" and bool(last_msg.content.strip()))

        # 분류기 전달용 가장 최근 유저 프롬프트 추출
        user_prompt = ""
        for msg in reversed(unified_request.messages):
            if msg.role == "user" and msg.content.strip():
                user_prompt = msg.content.strip()
                break

        # 서브 스텝 오토스케일링용 텍스트 추출:
        # 신규 유저 턴인 경우 유저 프롬프트를 사용하고, 내부 릴레이 스텝인 경우 가장 최근의 서브 액션 텍스트 추출
        substep_prompt = user_prompt
        if not is_new_user_turn and unified_request.messages:
            for msg in reversed(unified_request.messages):
                txt = msg.content.strip()
                if txt and not ("너는 비용 절감용 라우터다" in txt or "LUNA:LOW" in txt):
                    substep_prompt = txt
                    break

        return user_prompt, is_new_user_turn, substep_prompt

    @classmethod
    async def classify_request(
        cls, 
        unified_request: UnifiedRequest, 
        auth_token: str, 
        enterprise_api_url: str,
        account_id: str = None,
        requested_model: str = "",
        session_id: str = ""
    ) -> Tuple[str, str, str]:
        """
        요청 난이도를 판정하여 3-Tier (luna->terra) 또는 4-Tier (luna->terra->sol) 라우팅을 수행합니다.
        requested_model: Codex CLI 시점에 지정된 모델명 (e.g. gpt-5.6-sol, 4tier)
        """
        user_prompt, is_new_user_turn, substep_prompt = cls.extract_user_prompt_and_turn_status(unified_request)
        
        # CLI 실행 시점에 4-Tier Sol 라우터 활성화 여부 판별 (--model super, --model gpt-5.6-sol, --model 4tier)
        req_clean = (requested_model or unified_request.model or "").lower()
        is_4tier_sol_mode = (
            req_clean in ("gpt-5.6-sol", "4tier", "sol", "super", "high-power")
            or os.getenv("ROUTING_MODE", "").lower() in ("high_power", "4tier", "sol", "super")
            or os.getenv("HIGH_POWER_MODE", "").lower() == "true"
        )

        # 평가 대상 프롬프트: 턴의 첫 요청은 user_prompt, 내부 릴레이 서브 스텝은 substep_prompt 사용
        target_eval_prompt = user_prompt if is_new_user_turn else substep_prompt
        if not target_eval_prompt:
            return "LUNA:LOW", "gpt-5.6-luna", "low"
            
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        # 지능형 라우터 프롬프트 설정 (서브 스텝 자동 강하 지침 포함)
        payload = {
            "model": "gpt-5.6-luna",
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low"},
            "instructions": (
                "너는 비용 절감용 라우터다. 유저 요청 및 에이전트 서브 스텝을 가장 낮은 적절한 등급으로 정확하게 분류해라.\n"
                "반드시 아래 규칙을 지켜라.\n"
                "1) 명확한 근거가 없으면 더 낮은 등급을 선택한다.\n"
                "2) 단순 오타, 가벼운 수정, 파일 읽기/조회, 단순 서브 스텝 및 단순 설명은 LUNA:LOW로 분류한다.\n"
                "3) 표준적인 비즈니스 로직 단위 구현 및 리팩토링은 LUNA:MEDIUM으로 분류한다.\n"
                "4) 중간 이상의 복잡도, 아키텍처 변경, 복수 파일/컴포넌트 연동 수정은 TERRA:MEDIUM으로 승격한다.\n"
                "5) 다중 모듈 알고리즘 작성 및 하이레벨 아키텍처 설계는 TERRA:HIGH로 분류한다.\n"
                "6) 심층 최적화, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅은 EXTRA_HIGH로 분류한다.\n"
                "7) 오직 한 단어만 출력한다. 다른 설명은 절대 금지한다.\n\n"
                "- LUNA:LOW : 단순 문법, 간단한 오타 수정, 명령어 상식 가이드, 단순 스크립트 작성, 서브 스텝 툴 액션\n"
                "- LUNA:MEDIUM : 일반적인 비즈니스 로직 단위 업무 구현, 표준적인 리팩토링, 단일 파일 디버깅\n"
                "- TERRA:MEDIUM : 중간 수준 아키텍처 변경, 복수 컴포넌트 간 연동 수정, 중간 난이도 디버깅\n"
                "- TERRA:HIGH : 복잡한 알고리즘 작성, 다중 컴포넌트 아키텍처 분석 및 시스템 설계\n"
                "- EXTRA_HIGH : 고성능 튜닝 및 성능 분석, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅 (최고 난이도)"
            ),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": target_eval_prompt
                        }
                    ]
                }
            ]
        }

        import asyncio
        from datetime import datetime

        verdict_text = "LUNA:LOW"
        max_retries = 2
        retry_delay = 0.5
        
        for attempt in range(max_retries + 1):
            verdict_accumulated = ""
            try:
                client = cls.get_client()
                async with client.stream("POST", enterprise_api_url, headers=headers, json=payload) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data_json = json.loads(data_str)
                                    if data_json.get("choices"):
                                        choice = data_json["choices"][0]
                                        content = choice.get("delta", {}).get("content", "")
                                        if content.strip():
                                            verdict_accumulated += content
                                        if choice.get("finish_reason") is not None:
                                            break
                                    elif data_json.get("type") == "response.output_text.done":
                                        verdict_accumulated = data_json.get("text", "")
                                        break
                                    elif data_json.get("type") == "response.output_text.delta":
                                        delta_text = data_json.get("delta")
                                        if isinstance(delta_text, str):
                                            verdict_accumulated += delta_text
                                except Exception:
                                    pass
                        if verdict_accumulated.strip():
                            verdict_text = verdict_accumulated
                            break
                        else:
                            print(f"[Warning] Classifier HTTP status {response.status_code} with empty body on attempt {attempt+1}/{max_retries+1}.")
                    else:
                        print(f"[Warning] Classifier HTTP status {response.status_code} on attempt {attempt+1}/{max_retries+1}.")
            except Exception as e:
                print(f"[Warning] Classifier connection error on attempt {attempt+1}/{max_retries+1}: {e} ({type(e).__name__}).")
            
            if attempt < max_retries:
                print(f"➔ [RETRY] 0.5초 후 분류기 재시도 발송... ({attempt+1}/{max_retries})")
                await asyncio.sleep(retry_delay)
            else:
                print(f"[Warning] All classifier retries failed. Falling back to LUNA:LOW.")
                return "LUNA:LOW", "gpt-5.6-luna", "low"

        verdict = verdict_text.strip().upper()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if is_new_user_turn and user_prompt:
            display_prompt = user_prompt.replace("\n", " ").strip()
        else:
            display_prompt = f"[Substep] {target_eval_prompt.replace('\n', ' ').strip()}"

        # 등급 판정 및 라우터 모드(3-Tier vs 4-Tier Sol)에 따른 매핑 (ModelRegistry 핫패치 수신)
        from src.tierbridge.model_registry import registry
        active_mapping = registry.get_active_mapping()

        if "SOL:EXTRA_HIGH" in verdict or ("EXTRA_HIGH" in verdict and is_4tier_sol_mode):
            tier_info = active_mapping.get("SOL:EXTRA_HIGH", {"model": "gpt-5.6-sol", "effort": "xhigh"})
            final_decision, final_model, final_effort = "SOL:EXTRA_HIGH", tier_info.get("model", "gpt-5.6-sol"), tier_info.get("effort", "xhigh")
        elif "TERRA:EXTRA_HIGH" in verdict or "EXTRA_HIGH" in verdict:
            tier_info = active_mapping.get("TERRA:HIGH", {"model": "gpt-5.6-terra", "effort": "high"})
            final_decision, final_model, final_effort = "TERRA:EXTRA_HIGH", tier_info.get("model", "gpt-5.6-terra"), tier_info.get("effort", "high")
        elif "TERRA:HIGH" in verdict or "HIGH" in verdict:
            tier_info = active_mapping.get("TERRA:HIGH", {"model": "gpt-5.6-terra", "effort": "high"})
            final_decision, final_model, final_effort = "TERRA:HIGH", tier_info.get("model", "gpt-5.6-terra"), tier_info.get("effort", "high")
        elif "TERRA:MEDIUM" in verdict or "TERRA" in verdict:
            tier_info = active_mapping.get("TERRA:MEDIUM", {"model": "gpt-5.6-terra", "effort": "medium"})
            final_decision, final_model, final_effort = "TERRA:MEDIUM", tier_info.get("model", "gpt-5.6-terra"), tier_info.get("effort", "medium")
        elif "LUNA:MEDIUM" in verdict:
            tier_info = active_mapping.get("LUNA:MEDIUM", {"model": "gpt-5.6-luna", "effort": "medium"})
            final_decision, final_model, final_effort = "LUNA:MEDIUM", tier_info.get("model", "gpt-5.6-luna"), tier_info.get("effort", "medium")
        else:
            tier_info = active_mapping.get("LUNA:LOW", {"model": "gpt-5.6-luna", "effort": "low"})
            final_decision, final_model, final_effort = "LUNA:LOW", tier_info.get("model", "gpt-5.6-luna"), tier_info.get("effort", "low")

        mode_tag = "4-TIER SOL ROUTER" if is_4tier_sol_mode else "STANDARD 3-TIER ROUTER"
        sid_tag = f" [sid: {session_id}]" if session_id else ""
        print(f"[{now_str}]{sid_tag} ➔ [DECISION: {mode_tag}] {final_decision} ({final_model}:{final_effort}) | \"{display_prompt}\"", flush=True)
        return final_decision, final_model, final_effort
