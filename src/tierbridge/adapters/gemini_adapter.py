import json
import httpx
from typing import Tuple
from tierbridge.adapters.base import BaseAdapter
from tierbridge.models import UnifiedRequest, Message

class GeminiAdapter(BaseAdapter):
    def to_unified_request(self, raw_request_body: dict) -> UnifiedRequest:
        messages = []
        system_instruction = None
        
        # Gemini systemInstruction 파싱
        system_inst = raw_request_body.get("systemInstruction", {})
        if isinstance(system_inst, dict):
            parts = system_inst.get("parts", [])
            if parts:
                system_instruction = parts[0].get("text")
                
        # Gemini contents 파싱
        for content in raw_request_body.get("contents", []):
            role_raw = content.get("role", "user")
            # user -> user, model -> assistant
            role = "assistant" if role_raw == "model" else "user"
            parts = content.get("parts", [])
            if parts:
                text = parts[0].get("text", "")
                messages.append(Message(role=role, content=text))
                
        # config 파싱
        config = raw_request_body.get("generationConfig", {})
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("maxOutputTokens", 4096)
        
        return UnifiedRequest(
            system_instruction=system_instruction,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,  # Gemini/Vertex CLI는 기본적으로 스트리밍을 많이 요구함
            model="gemini-1.5-flash",
            raw_extra={k: v for k, v in raw_request_body.items() if k not in ["contents", "systemInstruction", "generationConfig"]}
        )

    def from_unified_request(self, unified_request: UnifiedRequest) -> dict:
        contents = []
        for msg in unified_request.messages:
            # assistant -> model
            role = "model" if msg.role == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content}]
            })
            
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": unified_request.temperature,
                "maxOutputTokens": unified_request.max_tokens
            }
        }
        
        if unified_request.system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": unified_request.system_instruction}]
            }
            
        if unified_request.raw_extra:
            payload.update(unified_request.raw_extra)
            
        return payload

    async def send_request(self, payload: dict, headers: dict, target_url: str) -> httpx.Response:
        # 실험용이므로 mock 호출 또는 패스스루
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.post(target_url, json=payload, headers=headers)

    def parse_stream_chunk(self, chunk_text: str) -> Tuple[str, bool]:
        """
        Gemini 스트림 청크 파싱 예시:
        data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}
        """
        if not chunk_text.startswith("data: "):
            return "", False
            
        data_str = chunk_text[6:].strip()
        if not data_str or data_str == "[DONE]":
            return "", True
            
        try:
            data_json = json.loads(data_str)
            candidates = data_json.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", ""), False
        except Exception:
            pass
            
        return "", False

    def format_stream_chunk(self, text: str, is_done: bool) -> str:
        """
        Gemini 에이전트(agy) 규격이 기대하는 SSE 청크 포맷팅
        """
        if is_done:
            return "data: [DONE]\n\n"
            
        chunk_data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": text}]
                    }
                }
            ]
        }
        return f"data: {json.dumps(chunk_data)}\n\n"
