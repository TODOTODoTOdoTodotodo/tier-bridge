import json
import httpx
from typing import Dict, Any, Optional
from tierbridge.classifier.interfaces import IClassifierStage, ClassificationContext, StageDecision

class DeepPathStage(IClassifierStage):
    """
    Stage 5: LLM 기반 의미론적 심층 판정 (gpt-reserve -> gpt-5.6-luna fallback)
    """
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        try:
            from tierbridge.router import Router
            return Router.get_client()
        except ImportError:
            from src.tierbridge.router import Router
            return Router.get_client()

    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> StageDecision:
        headers = {
            "Authorization": ctx.auth_token,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if ctx.account_id:
            headers["chatgpt-account-id"] = ctx.account_id

        payload = {
            "model": "gpt-reserve",
            "store": False,
            "stream": True,
            "reasoning": {"effort": "low"},
            "instructions": (
                "너는 비용 절감용 라우터다. 유저 요청 및 에이전트 서브 스텝을 가장 적절한 게이밍 랭크 티어로 정확하게 분류해라.\n"
                "반드시 아래 규칙을 지켜라.\n"
                "1) 명확한 근거가 없으면 더 낮은 랭크 등급(BRONZE)을 선택한다.\n"
                "2) 단순 오타, 가벼운 수정, 파일 읽기/조회, 단순 서브 스텝 및 단순 설명은 BRONZE로 분류한다.\n"
                "3) 표준적인 비즈니스 로직 단위 구현 및 단일 파일 리팩토링은 SILVER로 분류한다.\n"
                "4) 중간 이상의 복잡도, 아키텍처 변경, 복수 파일/컴포넌트 연동 수정은 GOLD로 승격한다.\n"
                "5) 다중 모듈 알고리즘 작성 및 하이레벨 아키텍처 설계는 PLATINUM으로 분류한다.\n"
                "6) 심층 최적화, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅은 CHALLENGER 또는 DIAMOND로 분류한다.\n"
                "7) 오직 한 단어만 출력한다. (BRONZE, SILVER, GOLD, PLATINUM, DIAMOND, CHALLENGER). 다른 설명은 절대 금지한다.\n\n"
                "- BRONZE : 단순 문법, 간단한 오타 수정, 명령어 상식 가이드, 단순 스크립트 작성, 서브 스텝 툴 액션\n"
                "- SILVER : 일반적인 비즈니스 로직 단위 업무 구현, 표준적인 리팩토링, 단일 파일 디버깅\n"
                "- GOLD : 중간 수준 아키텍처 변경, 복수 컴포넌트 간 연동 수정, 중간 난이도 디버깅\n"
                "- PLATINUM : 복잡한 알고리즘 작성, 다중 컴포넌트 아키텍처 분석 및 시스템 설계\n"
                "- DIAMOND / CHALLENGER : 고성능 튜닝 및 성능 분석, 메모리 누수 탐지, 교착상태(Deadlock) 디버깅 (최고 난이도)"
            ),
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": ctx.target_eval_prompt}]
                }
            ]
        }

        candidate_models = ["gpt-reserve", "gpt-5.6-luna"]
        classifier_model_used = None
        verdict_text = ""

        for cand_idx, cand_model in enumerate(candidate_models):
            payload["model"] = cand_model
            verdict_accumulated = ""
            try:
                client = self.get_client()
                async with client.stream("POST", ctx.enterprise_api_url, headers=headers, json=payload) as response:
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
                            verdict_text = verdict_accumulated.strip().upper()
                            classifier_model_used = cand_model if cand_idx == 0 else f"{cand_model}-fallback"
                            break
            except Exception:
                pass

        if not verdict_text:
            classifier_model_used = "fail-safe"
            verdict_text = "BRONZE"

        # 허용된 티어로 정규화
        normalized_tier = "BRONZE"
        for t in ["CHALLENGER", "DIAMOND", "PLATINUM", "GOLD", "SILVER", "BRONZE"]:
            if t in verdict_text:
                normalized_tier = t
                break

        return StageDecision(
            handled=True,
            tier=normalized_tier,
            stage_name="deep_path",
            reason=f"LLM deep evaluation using {classifier_model_used}",
            confidence=0.95,
            metadata={"classifier_model_used": classifier_model_used, "raw_verdict": verdict_text}
        )
