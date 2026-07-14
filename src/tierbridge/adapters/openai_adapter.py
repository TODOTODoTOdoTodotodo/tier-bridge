import json
import httpx
from typing import Tuple
from tierbridge.adapters.base import BaseAdapter
from tierbridge.models import UnifiedRequest, Message

class OpenAIAdapter(BaseAdapter):
    def to_unified_request(self, raw_request_body: dict) -> UnifiedRequest:
        messages = []
        system_instruction = None
        
        for msg in raw_request_body.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_instruction = content
            else:
                messages.append(Message(role=role, content=content))
                
        return UnifiedRequest(
            system_instruction=system_instruction,
            messages=messages,
            temperature=raw_request_body.get("temperature", 0.7),
            max_tokens=raw_request_body.get("max_tokens", 4096),
            stream=raw_request_body.get("stream", False),
            model=raw_request_body.get("model"),
            raw_extra={k: v for k, v in raw_request_body.items() if k not in ["messages", "temperature", "max_tokens", "stream", "model"]}
        )

    def from_unified_request(self, unified_request: UnifiedRequest) -> dict:
        messages = []
        if unified_request.system_instruction:
            messages.append({"role": "system", "content": unified_request.system_instruction})
            
        for msg in unified_request.messages:
            messages.append({"role": msg.role, "content": msg.content})
            
        payload = {
            "model": unified_request.model,
            "messages": messages,
            "temperature": unified_request.temperature,
            "max_tokens": unified_request.max_tokens,
            "stream": unified_request.stream
        }
        
        # 오리지널 요청에 있던 추가 필드를 병합
        if unified_request.raw_extra:
            payload.update(unified_request.raw_extra)
            
        return payload

    async def send_request(self, payload: dict, headers: dict, target_url: str) -> httpx.Response:
        # FastAPI Uvicorn과 외부 http 비동기 스트리밍 연동용
        # stream 옵션은 호출 측(stream_transpiler나 harness.py)에서 직접 stream_generator로 분기 처리할 것이므로, 
        # 여기서는 단순 POST 헬퍼 역할만 수행합니다.
        async with httpx.AsyncClient(timeout=180.0) as client:
            return await client.post(target_url, json=payload, headers=headers)

    def parse_stream_chunk(self, chunk_text: str) -> Tuple[str, bool]:
        """
        OpenAI 표준 규격 및 ChatGPT Enterprise 규격의 스트림 청크 문자열을 모두 파싱합니다.
        """
        lines = chunk_text.splitlines()
        data_str = ""
        is_done = False
        
        for line in lines:
            line = line.strip()
            if line.startswith("data:"):
                temp_data = line[5:].strip()
                if temp_data == "[DONE]":
                    is_done = True
                else:
                    data_str = temp_data
                break
                
        if is_done:
            return "", True
            
        if not data_str:
            return "", False
            
        try:
            data_json = json.loads(data_str)
            
            # 1. 표준 OpenAI chat completions 규격
            if "choices" in data_json:
                choices = data_json.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    return content, False
                    
            # 2. ChatGPT Enterprise 규격 (response.content_part.delta 등)
            elif "delta" in data_json:
                delta = data_json.get("delta", {})
                if delta.get("type") == "text":
                    return delta.get("text", ""), False
                return delta.get("text", ""), False
                
        except Exception:
            pass
            
        return "", False

    def format_stream_chunk(self, text: str, is_done: bool) -> str:
        """
        클라이언트 에이전트(OpenAI 호환)가 기대하는 OpenAI 포맷 SSE 청크 렌더링
        """
        if is_done:
            return "data: [DONE]\n\n"
            
        chunk_data = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": None
                }
            ]
        }
        return f"data: {json.dumps(chunk_data)}\n\n"
