from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from tierbridge.models import UnifiedRequest, Message

@dataclass
class ClassificationContext:
    unified_request: UnifiedRequest
    user_prompt: str
    is_new_user_turn: bool
    substep_prompt: str
    target_eval_prompt: str
    total_input_tokens: int = 0
    session_id: str = ""
    requested_model: str = ""
    auth_token: str = ""
    enterprise_api_url: str = ""
    account_id: Optional[str] = None
    credit_remaining_percent: Optional[float] = None
    is_4tier_sol_mode: bool = False

@dataclass
class StageDecision:
    handled: bool
    tier: Optional[str] = None
    stage_name: str = ""
    reason: str = ""
    confidence: float = 1.0
    escalated_from: Optional[str] = None
    governor_mode: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class IClassifierStage(ABC):
    """
    SOLID ISP/LSP: 분류 파이프라인의 각 단계가 준수해야 하는 단일 책임 계약 인터페이스
    """
    @abstractmethod
    async def evaluate(self, ctx: ClassificationContext, policy: Dict[str, Any]) -> Optional[StageDecision]:
        pass
