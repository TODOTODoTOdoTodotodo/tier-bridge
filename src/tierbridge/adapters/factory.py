from tierbridge.adapters.base import BaseAdapter
from tierbridge.adapters.openai_adapter import OpenAIAdapter
from tierbridge.adapters.anthropic_adapter import AnthropicAdapter
from tierbridge.adapters.gemini_adapter import GeminiAdapter

class AdapterFactory:
    # 각 어댑터 인스턴스를 하나만 캐싱하여 재사용 (Memory Efficiency)
    _registry = {
        "openai": OpenAIAdapter(),
        "anthropic": AnthropicAdapter(),
        "gemini": GeminiAdapter()
    }

    @classmethod
    def get_adapter(cls, vendor_type: str) -> BaseAdapter:
        vendor_lower = vendor_type.lower()
        
        # 유연한 벤더 키 매핑
        if "openai" in vendor_lower or "codex" in vendor_lower:
            key = "openai"
        elif "anthropic" in vendor_lower or "claude" in vendor_lower:
            key = "anthropic"
        elif "gemini" in vendor_lower or "vertex" in vendor_lower or "google" in vendor_lower:
            key = "gemini"
        else:
            key = vendor_lower

        adapter = cls._registry.get(key)
        if not adapter:
            raise ValueError(f"지원되지 않는 벤더 타입입니다: {vendor_type}")
        return adapter
