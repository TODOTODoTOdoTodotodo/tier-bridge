from pydantic import BaseModel
from typing import List, Dict, Optional, Any

class Message(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str

class UnifiedRequest(BaseModel):
    system_instruction: Optional[str] = None
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 4096
    stream: Optional[bool] = False
    model: Optional[str] = None
    raw_extra: Optional[Dict[str, Any]] = None  # 오리지널 요청의 기타 필드 보존용
