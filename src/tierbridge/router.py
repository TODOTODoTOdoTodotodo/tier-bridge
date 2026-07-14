import os
import json
import httpx
from typing import Tuple
from tierbridge.models import UnifiedRequest

class Router:
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
            return "LOW", "gpt-4o-mini", "low"
            
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

        verdict_text = "MINI"  # 기본 폴백값
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("POST", enterprise_api_url, headers=headers, json=payload, timeout=8.0) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:].strip()
                                if data_str == "[DONE]":
                                    continue
                                try:
                                    data_json = json.loads(data_str)
                                    # Streaming Delta 파싱
                                    if data_json.get("choices"):
                                        choice = data_json["choices"][0]
                                        content = choice.get("delta", {}).get("content", "")
                                        if content.strip():
                                            verdict_text += content
                                    # response.completed 등의 done 이벤트 처리
                                    elif data_json.get("type") == "response.output_text.done":
                                        verdict_text = data_json.get("text", "")
                                    elif data_json.get("type") == "response.output_text.delta":
                                        delta_text = data_json.get("delta")
                                        if isinstance(delta_text, str):
                                            verdict_text += delta_text
                                except Exception:
                                    pass
                    else:
                        print(f"[Warning] Classifier HTTP status {response.status_code}. Fallback to MINI.")
        except Exception as e:
            print(f"[Warning] Classifier connection error: {e}. Fallback to MINI.")

        # 공백 제거 및 대문자 변환
        verdict = verdict_text.strip().upper()
        print(f"➔ [DECISION] 추정된 등급: {verdict}")

        # 3-Tier 매핑 정책 적용
        # LOW: MINI, LUNA:LOW
        # MID: LUNA:MEDIUM, TERRA:MEDIUM
        # HIGH: TERRA:HIGH, TERRA:EXTRA_HIGH, TERRA:MAX
        if "MINI" in verdict or "LUNA:LOW" in verdict:
            # Low Tier -> gpt-4o-mini, low effort
            return "LOW", "gpt-4o-mini", "low"
        elif "LUNA:MEDIUM" in verdict or "TERRA:MEDIUM" in verdict:
            # Mid Tier -> gpt-4o-mini-high (gpt-4o-mini with medium effort)
            return "MID", "gpt-4o-mini", "medium"
        else:
            # High Tier -> gpt-4o (or gpt-5.6-terra) with high effort
            # 기존 mock_mode와 엔터프라이즈 모드를 호환하기 위해, 타겟 모델 식별자를 결정합니다.
            return "HIGH", "gpt-5.6-terra", "high"
