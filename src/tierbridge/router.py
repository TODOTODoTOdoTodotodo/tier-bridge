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
            # 25초 타임아웃과 연결 풀 설정으로 재사용 최적화
            cls._client = httpx.AsyncClient(
                timeout=httpx.Timeout(25.0, connect=10.0),
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
            # 텍스트가 없는 경우 기본 안전값 제공
            return "MINI", "gpt-5.4-mini", "low"
            
        headers = {
            "Authorization": auth_token,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        # 분류를 위한 gpt-5.4-mini 프롬프트 설정 (기존 규칙 재사용)
        payload = {
            "model": "gpt-5.4-mini",
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low"},
            "instructions": (
                "너는 비용 절감용 라우터다. 유저 요청을 가장 낮은 적절한 등급으로 분류해라.\n"
                "반드시 아래 규칙을 지켜라.\n"
                "1) 명확한 근거가 없으면 더 낮은 등급을 선택한다.\n"
                "2) 구현, 리팩토링, 일반적인 버그 수정은 기본적으로 LUNA 이하로 분류한다.\n"
                "3) 성능, 동시성, 교착상태, 메모리 누수, 대규모 최적화, 아키텍처 설계가 명시된 경우에만 TERRA를 사용한다.\n"
                "4) 중간 수준의 업무는 `LOW`보다 `MEDIUM`을 우선한다.\n"
                "5) 복수 파일 변경, 중간 난이도 디버깅, 일반적인 서비스 로직 개선은 `LUNA:MEDIUM`으로 분류한다.\n"
                "6) 아키텍처 변경이 있지만 최고 난도는 아닌 경우는 `TERRA:MEDIUM`으로 분류한다.\n"
                "7) 단순 문법 수정, 오타 수정, 명령어 설명은 MINI다.\n"
                "8) 오직 한 단어만 출력한다. 다른 설명은 절대 금지한다.\n\n"
                "- MINI : 단순 문법, 간단한 오타 수정, 명령어 상식 가이드\n"
                "- LUNA:LOW : 단순 기능 구현 스크립트 작성, 가벼운 포맷팅 변경\n"
                "- LUNA:MEDIUM : 일반적인 비즈니스 로직 단위 업무 구현, 표준적인 리팩토링\n"
                "- TERRA:MEDIUM : 중간 수준 아키텍처 변경, 복수 컴포넌트 간 연동 수정, 일반적 중간 난이도 디버깅\n"
                "- TERRA:HIGH : 복잡한 알고리즘 작성, 다중 컴포넌트 아키텍처 분석 및 설계\n"
                "- TERRA:EXTRA_HIGH : 고성능 튜닝 및 성능 분석, 메모리 누수 탐지 등 심층 최적화 디버깅\n"
                "- TERRA:MAX : 교착상태(Deadlock) 디버깅, 대규모 레이턴시 최적화, 딥 트러블슈팅"
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

        verdict_text = "MINI"  # 기본 폴백값 (저비용 모델 안전 규격)
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
                    else:
                        print(f"[Warning] Classifier HTTP status {response.status_code}. Fallback to MINI.")
                        return "MINI", "gpt-5.4-mini", "low"
        except Exception as e:
            print(f"[Warning] Classifier connection error: {e} ({type(e).__name__}). Fallback to MINI.")
            return "MINI", "gpt-5.4-mini", "low"

        # 공백 제거 및 대문자 변환
        verdict = verdict_text.strip().upper()
        print(f"➔ [DECISION] 추정된 등급: {verdict}")

        # 3-Tier 매핑 정책 적용
        # 설계서의 Model & Reasoning Effort Mapping Rules 준수
        if "MINI" in verdict:
            return "MINI", "gpt-5.4-mini", "low"
        elif "LUNA:LOW" in verdict:
            return "LUNA:LOW", "gpt-5.6-luna", "low"
        elif "LUNA:MEDIUM" in verdict:
            return "LUNA:MEDIUM", "gpt-5.6-luna", "medium"
        elif "TERRA:MEDIUM" in verdict:
            return "TERRA:MEDIUM", "gpt-5.6-terra", "medium"
        elif "TERRA:HIGH" in verdict:
            return "TERRA:HIGH", "gpt-5.6-terra", "high"
        elif "TERRA:EXTRA_HIGH" in verdict:
            return "TERRA:EXTRA_HIGH", "gpt-5.6-terra", "extra_high"
        elif "TERRA:MAX" in verdict:
            return "TERRA:MAX", "gpt-5.6-terra", "max"
        else:
            # Fallback (설계서: gpt-5.6-terra, max)
            return verdict, "gpt-5.6-terra", "max"
