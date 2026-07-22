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
    def extract_user_prompt(unified_request: UnifiedRequest) -> str:
        """가장 최근의 사용자 질의를 추출합니다."""
        for msg in reversed(unified_request.messages):
            if msg.role == "user" and msg.content.strip():
                return msg.content.strip()
        return ""

    @classmethod
    async def classify_request(
        cls, 
        unified_request: UnifiedRequest, 
        auth_token: str, 
        enterprise_api_url: str,
        account_id: str = None
    ) -> Tuple[str, str, str]:
        """
        요청 난이도를 분류하여 (최종_결정_등급, 타겟_모델_식별자, reasoning_effort) 튜플을 반환합니다.
        등급: LOW, MID, HIGH
        """
        user_prompt = cls.extract_user_prompt(unified_request)
        if not user_prompt:
            # 텍스트가 없는 경우 기본 안전값 제공 (최저 등급: LUNA:LOW)
            return "LUNA:LOW", "gpt-5.6-luna", "low"
            
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        # 분류를 위한 gpt-5.6-luna (low effort) 프롬프트 설정
        payload = {
            "model": "gpt-5.6-luna",
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low"},
            "instructions": (
                "너는 비용 절감용 라우터다. 유저 요청을 가장 낮은 적절한 등급으로 정확하게 분류해라.\n"
                "반드시 아래 규칙을 지켜라.\n"
                "1) 명확한 근거가 없으면 더 낮은 등급을 선택한다.\n"
                "2) 단순 오타, 가벼운 수정, 단순 설명은 LUNA:LOW로 분류한다.\n"
                "3) 표준적인 비즈니스 로직 단위 구현 및 리팩토링은 LUNA:MEDIUM으로 분류한다.\n"
                "4) 중간 이상의 복잡도, 아키텍처 변경, 복수 파일/컴포넌트 연동 수정부터 TERRA:MEDIUM으로 승격한다.\n"
                "5) 다중 모듈 알고리즘 작성 및 하이레벨 아키텍처 설계는 TERRA:HIGH로 분류한다.\n"
                "6) 심층 최적화, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅은 TERRA:EXTRA_HIGH로 분류한다.\n"
                "7) 오직 한 단어만 출력한다. 다른 설명은 절대 금지한다.\n\n"
                "- LUNA:LOW : 단순 문법, 간단한 오타 수정, 명령어 상식 가이드, 단순 스크립트 작성 (최저 등급)\n"
                "- LUNA:MEDIUM : 일반적인 비즈니스 로직 단위 업무 구현, 표준적인 리팩토링, 단일 파일 디버깅\n"
                "- TERRA:MEDIUM : 중간 수준 아키텍처 변경, 복수 컴포넌트 간 연동 수정, 중간 난이도 디버깅\n"
                "- TERRA:HIGH : 복잡한 알고리즘 작성, 다중 컴포넌트 아키텍처 분석 및 시스템 설계\n"
                "- TERRA:EXTRA_HIGH : 고성능 튜닝 및 성능 분석, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅 (최대 등급)"
            ),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_prompt
                        }
                    ]
                }
            ]
        }

        import asyncio

        verdict_text = "LUNA:LOW"  # 기본 폴백값 (저비용 모델 안전 규격)
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
                                    # 1. Streaming Delta 파싱 (OpenAI)
                                    if data_json.get("choices"):
                                        choice = data_json["choices"][0]
                                        content = choice.get("delta", {}).get("content", "")
                                        if content.strip():
                                            verdict_accumulated += content
                                        if choice.get("finish_reason") is not None:
                                            break
                                    # 2. response.output_text.done (ChatGPT Enterprise 완료)
                                    elif data_json.get("type") == "response.output_text.done":
                                        verdict_accumulated = data_json.get("text", "")
                                        break
                                    # 3. response.output_text.delta (ChatGPT Enterprise 진행)
                                    elif data_json.get("type") == "response.output_text.delta":
                                        delta_text = data_json.get("delta")
                                        if isinstance(delta_text, str):
                                            verdict_accumulated += delta_text
                                except Exception:
                                    pass
                        if verdict_accumulated.strip():
                            verdict_text = verdict_accumulated
                            break  # 성공했으므로 시도 루프 탈출
                        else:
                            print(f"[Warning] Classifier HTTP status {response.status_code} with empty body on attempt {attempt+1}/{max_retries+1}.")
                    else:
                        print(f"[Warning] Classifier HTTP status {response.status_code} on attempt {attempt+1}/{max_retries+1}.")
            except Exception as e:
                print(f"[Warning] Classifier connection error on attempt {attempt+1}/{max_retries+1}: {e} ({type(e).__name__}).")
            
            # 재시도 딜레이 적용
            if attempt < max_retries:
                print(f"➔ [RETRY] 0.5초 후 분류기 재시도 발송... ({attempt+1}/{max_retries})")
                await asyncio.sleep(retry_delay)
            else:
                print(f"[Warning] All classifier retries failed. Falling back to LUNA:LOW.")
                return "LUNA:LOW", "gpt-5.6-luna", "low"

        # 공백 제거 및 대문자 변환
        verdict = verdict_text.strip().upper()
        print(f"➔ [DECISION] 추정된 등급: {verdict}")

        # 3-Tier 매핑 정책 적용
        if "LUNA:LOW" in verdict or "MINI" in verdict:
            return "LUNA:LOW", "gpt-5.6-luna", "low"
        elif "LUNA:MEDIUM" in verdict:
            return "LUNA:MEDIUM", "gpt-5.6-luna", "medium"
        elif "TERRA:MEDIUM" in verdict:
            return "TERRA:MEDIUM", "gpt-5.6-terra", "medium"
        elif "TERRA:HIGH" in verdict:
            return "TERRA:HIGH", "gpt-5.6-terra", "high"
        elif "TERRA:EXTRA_HIGH" in verdict or "TERRA:XHIGH" in verdict or "TERRA:MAX" in verdict:
            return "TERRA:EXTRA_HIGH", "gpt-5.6-terra", "extra_high"
        else:
            return "LUNA:LOW", "gpt-5.6-luna", "low"
