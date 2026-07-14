import json
import httpx
from typing import Tuple
from tierbridge.adapters.base import BaseAdapter
from tierbridge.models import UnifiedRequest, Message

class AnthropicAdapter(BaseAdapter):
    def to_unified_request(self, raw_request_body: dict) -> UnifiedRequest:
        messages = []
        system_instruction = raw_request_body.get("system")
        
        for msg in raw_request_body.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # assistant -> assistant
            role_mapped = "assistant" if role == "assistant" else "user"
            messages.append(Message(role=role_mapped, content=content))
            
        return UnifiedRequest(
            system_instruction=system_instruction,
            messages=messages,
            temperature=raw_request_body.get("temperature", 0.7),
            max_tokens=raw_request_body.get("max_tokens", 4096),
            stream=raw_request_body.get("stream", False),
            model=raw_request_body.get("model"),
            raw_extra={k: v for k, v in raw_request_body.items() if k not in ["messages", "system", "temperature", "max_tokens", "stream", "model"]}
        )

    def from_unified_request(self, unified_request: UnifiedRequest) -> dict:
        messages = []
        for msg in unified_request.messages:
            messages.append({"role": msg.role, "content": msg.content})
            
        payload = {
            "model": unified_request.model or "claude-3-5-sonnet",
            "messages": messages,
            "temperature": unified_request.temperature,
            "max_tokens": unified_request.max_tokens,
            "stream": unified_request.stream
        }
        
        if unified_request.system_instruction:
            payload["system"] = unified_request.system_instruction
            
        if unified_request.raw_extra:
            payload.update(unified_request.raw_extra)
            
        return payload

    async def send_request(self, payload: dict, headers: dict, target_url: str) -> httpx.Response:
        # 실험용이므로 mock 응답 생성 처리
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 외부 백엔드 연동을 원한다면 실제 API 호출이 가능하지만, 우선 Mock 모드로 시뮬레이션
            return await client.post(target_url, json=payload, headers=headers)

    def parse_stream_chunk(self, chunk_text: str) -> Tuple[str, bool]:
        """
        Anthropic 스트림 청크 파싱 예시:
        event: content_block_delta
        data: {"delta": {"text": "Hello"}}
        """
        if "content_block_delta" not in chunk_text:
            return "", False
            
        lines = chunk_text.splitlines()
        for line in lines:
            if line.startswith("data:"):
                try:
                    data_str = line[5:].strip()
                    data_json = json.loads(data_str)
                    text = data_json.get("delta", {}).get("text", "")
                    return text, False
                except Exception:
                    pass
        return "", False

    def format_stream_chunk(self, text: str, is_done: bool) -> str:
        """
        Claude Code 등 Anthropic 포맷을 기대하는 클라이언트를 위한 SSE 청크 포맷팅
        """
        if is_done:
            return "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n"
            
        chunk_data = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {
                "type": "text_delta",
                "text": text
            }
        }
        return f"event: content_block_delta\ndata: {json.dumps(chunk_data)}\n\n"
