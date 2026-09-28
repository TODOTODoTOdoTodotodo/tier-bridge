import os
import json
import httpx
from datetime import datetime
from typing import Tuple
from tierbridge.models import UnifiedRequest

class Router:
    _client = None
    last_classifier_status = {
        "primary": "gpt-reserve",
        "fallback": "gpt-5.6-luna",
        "last_used": "gpt-reserve",
        "last_timestamp": None
    }

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
                if txt and not ("너는 비용 절감용 라우터다" in txt or "BRONZE" in txt):
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
            try:
                from tierbridge.model_registry import registry
            except ImportError:
                from src.tierbridge.model_registry import registry
            active_mapping = registry.get_active_mapping()
            tier_info = active_mapping.get("BRONZE", {"model": "gpt-6-luna", "effort": "low"})
            return "BRONZE", tier_info.get("model", "gpt-6-luna"), tier_info.get("effort", "low")

        # 5단계 SOLID 분류 파이프라인 컨텍스트 구성
        total_tokens = sum([max(1, len(m.content) // 4) for m in unified_request.messages if m.content])

        try:
            from src.tierbridge.classifier.interfaces import ClassificationContext
            from src.tierbridge.classifier.pipeline import ClassifierPipeline
        except ImportError:
            from tierbridge.classifier.interfaces import ClassificationContext
            from tierbridge.classifier.pipeline import ClassifierPipeline

        ctx = ClassificationContext(
            unified_request=unified_request,
            user_prompt=user_prompt,
            is_new_user_turn=is_new_user_turn,
            substep_prompt=substep_prompt,
            target_eval_prompt=target_eval_prompt,
            total_input_tokens=total_tokens,
            session_id=session_id,
            requested_model=requested_model,
            auth_token=auth_token,
            enterprise_api_url=enterprise_api_url,
            account_id=account_id,
            is_4tier_sol_mode=is_4tier_sol_mode
        )

        pipeline = ClassifierPipeline()
        verdict, classifier_model_used, meta = await pipeline.classify(ctx)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cls.last_classifier_status["last_used"] = classifier_model_used
        cls.last_classifier_status["last_timestamp"] = now_str
        cls.last_classifier_status["telemetry"] = pipeline.get_telemetry()

        if is_new_user_turn and user_prompt:
            display_prompt = user_prompt.replace("\n", " ").strip()
        else:
            display_prompt = f"[Substep] {target_eval_prompt.replace('\n', ' ').strip()}"

        try:
            from tierbridge.model_registry import registry
        except ImportError:
            from src.tierbridge.model_registry import registry
        active_mapping = registry.get_active_mapping()

        if "CHALLENGER" in verdict or ("EXTRA_HIGH" in verdict and is_4tier_sol_mode):
            tier_info = active_mapping.get("CHALLENGER", {"model": "gpt-6-sol", "effort": "xhigh"})
            final_decision, final_model, final_effort = "CHALLENGER", tier_info.get("model", "gpt-6-sol"), tier_info.get("effort", "xhigh")
        elif "DIAMOND" in verdict:
            tier_info = active_mapping.get("DIAMOND", active_mapping.get("PLATINUM", {"model": "gpt-6-sol", "effort": "high"}))
            final_decision, final_model, final_effort = "DIAMOND", tier_info.get("model", "gpt-6-sol"), tier_info.get("effort", "high")
        elif "PLATINUM" in verdict or "HIGH" in verdict:
            tier_info = active_mapping.get("PLATINUM", {"model": "gpt-6-sol", "effort": "medium"})
            final_decision, final_model, final_effort = "PLATINUM", tier_info.get("model", "gpt-6-sol"), tier_info.get("effort", "medium")
        elif "GOLD" in verdict or "TERRA" in verdict:
            tier_info = active_mapping.get("GOLD", {"model": "gpt-6-sol", "effort": "low"})
            final_decision, final_model, final_effort = "GOLD", tier_info.get("model", "gpt-6-sol"), tier_info.get("effort", "low")
        elif "SILVER" in verdict:
            tier_info = active_mapping.get("SILVER", {"model": "gpt-6-luna", "effort": "medium"})
            final_decision, final_model, final_effort = "SILVER", tier_info.get("model", "gpt-6-luna"), tier_info.get("effort", "medium")
        else:
            tier_info = active_mapping.get("BRONZE", {"model": "gpt-6-luna", "effort": "low"})
            final_decision, final_model, final_effort = "BRONZE", tier_info.get("model", "gpt-6-luna"), tier_info.get("effort", "low")

        mode_tag = "4-TIER SOL ROUTER" if is_4tier_sol_mode else "STANDARD 3-TIER ROUTER"
        sid_tag = f" [sid: {session_id}]" if session_id else ""
        print(f"[{now_str}]{sid_tag} ➔ [DECISION: {mode_tag}] {final_decision} ({final_model}:{final_effort}) [clf: {classifier_model_used}] | \"{display_prompt}\"", flush=True)

        # 에스컬레이션 또는 예산 조정 발생 시 상세 로깅
        if meta.get("escalated"):
            print(f"[{now_str}]{sid_tag} ➔ [CLASSIFIER ESCALATION] {meta.get('escalated_from')} ➔ {final_decision} ({meta.get('escalation_reason')})", flush=True)
        if meta.get("context_floor_applied"):
            print(f"[{now_str}]{sid_tag} ➔ [CONTEXT METRICS FLOOR] {meta.get('context_floor_applied')} ({meta.get('context_reason')})", flush=True)
        if meta.get("governor_clamped"):
            print(f"[{now_str}]{sid_tag} ➔ [BUDGET GOVERNOR] Clamped {meta.get('clamped_from')} ➔ {final_decision} ({meta.get('clamp_reason')})", flush=True)

        # 분류기 자체 소모 토큰 로깅 (Fast-path는 0, LLM 호출 시에만 산출, 가변 USD 생략)
        if classifier_model_used == "fast-path-regex":
            clf_in_tok, clf_out_tok = 0, 0
        else:
            clf_in_tok = max(100, int(len(target_eval_prompt) * 0.35)) + 150
            clf_out_tok = max(5, int(len(verdict) * 0.5))

        print(f"[{now_str}]{sid_tag} ➔ [USAGE] CLASSIFIER ({classifier_model_used}) | input={clf_in_tok} output={clf_out_tok} tokens | loc=0 lines", flush=True)

        return final_decision, final_model, final_effort
