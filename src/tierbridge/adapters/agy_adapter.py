import os
import json
import asyncio
from datetime import datetime
from typing import Tuple, AsyncGenerator, Optional
import httpx
from tierbridge.adapters.base import BaseAdapter
from tierbridge.models import UnifiedRequest, Message

class AgyAdapter(BaseAdapter):
    """
    Google Antigravity CLI(agy) 기반 Gemini 백엔드 어댑터.
    ChatGPT Enterprise 크레딧 고갈 시 투명 페일오버 및 직결 백엔드로 작동합니다.
    """
    def __init__(self, default_model: str = "gemini-3.8-flash-high"):
        self.default_model = default_model

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
                
        # ChatGPT responses 'input' 파싱 (messages가 비어 있는 경우 백업)
        if not messages and "input" in raw_request_body:
            for item in raw_request_body.get("input", []):
                role = item.get("role", "user")
                raw_content = item.get("content", [])
                parts_text = []
                if isinstance(raw_content, list):
                    for part in raw_content:
                        if isinstance(part, dict):
                            t = part.get("text", "")
                            if t:
                                parts_text.append(t)
                        elif isinstance(part, str) and part.strip():
                            parts_text.append(part.strip())
                    content_text = " ".join(parts_text)
                else:
                    content_text = str(raw_content)
                messages.append(Message(role=role, content=content_text))
                
        if not system_instruction and "instructions" in raw_request_body:
            system_instruction = str(raw_request_body["instructions"])

        model = raw_request_body.get("model") or self.default_model
        return UnifiedRequest(
            system_instruction=system_instruction,
            messages=messages,
            temperature=raw_request_body.get("temperature", 0.7),
            max_tokens=raw_request_body.get("max_tokens", 4096),
            stream=raw_request_body.get("stream", True),
            model=model,
            raw_extra={k: v for k, v in raw_request_body.items() if k not in ["messages", "temperature", "max_tokens", "stream", "model", "input", "instructions"]}
        )

    def from_unified_request(self, unified_request: UnifiedRequest) -> dict:
        prompt_parts = []
        if unified_request.system_instruction:
            prompt_parts.append(f"[System Instruction]\n{unified_request.system_instruction}\n")

        for msg in unified_request.messages:
            role_label = "User" if msg.role == "user" else ("Assistant" if msg.role == "assistant" else "System")
            prompt_parts.append(f"[{role_label}]:\n{msg.content}")

        full_prompt = "\n\n".join(prompt_parts)
        model = unified_request.model
        if not model or model in ("default", "latest") or "gpt" in str(model).lower() or "4tier" in str(model).lower() or "super" in str(model).lower():
            model = os.getenv("AGY_MODEL", self.default_model)

        return {
            "prompt": full_prompt,
            "model": model,
            "stream": unified_request.stream
        }

    async def stream_agy_process(self, prompt: str, model: str = None) -> AsyncGenerator[str, None]:
        target_model = model or os.getenv("AGY_MODEL", self.default_model)
        cmd = ["agy", "--model", target_model, "-p", prompt]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore")
                yield text
        finally:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except Exception:
                    pass

    async def send_request(self, payload: dict, headers: dict, target_url: str) -> httpx.Response:
        prompt = payload.get("prompt", "")
        model = payload.get("model", self.default_model)
        chunks = []
        async for chunk in self.stream_agy_process(prompt, model):
            chunks.append(chunk)
        full_text = "".join(chunks)
        response_dict = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": full_text},
                    "finish_reason": "stop"
                }
            ],
            "output_text": full_text
        }
        return httpx.Response(
            status_code=200,
            json=response_dict,
            request=httpx.Request("POST", target_url)
        )

    def parse_stream_chunk(self, chunk_text: str) -> Tuple[str, bool]:
        if chunk_text.strip() == "[DONE]":
            return "", True
        return chunk_text, False

    def format_stream_chunk(self, text: str, is_done: bool) -> str:
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

    async def generate_responses_sse_stream(self, prompt: str, model: str = None, on_chunk=None) -> AsyncGenerator[bytes, None]:
        """Codex CLI (/v1/responses) 규격 SSE 스트림 생성기"""
        resp_id = f"resp_agy_{int(datetime.now().timestamp() * 1000)}"
        yield f"data: {json.dumps({'type': 'response.created', 'response': {'id': resp_id, 'status': 'in_progress'}})}\n\n".encode("utf-8")
        yield f"data: {json.dumps({'type': 'response.output_item.added', 'item': {'type': 'message', 'role': 'assistant', 'content': []}})}\n\n".encode("utf-8")
        yield f"data: {json.dumps({'type': 'response.content_part.added', 'part': {'type': 'output_text', 'text': ''}})}\n\n".encode("utf-8")
        
        full_output = []
        async for chunk in self.stream_agy_process(prompt, model):
            full_output.append(chunk)
            if on_chunk:
                on_chunk(chunk.encode("utf-8"))
            yield f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': chunk})}\n\n".encode("utf-8")

        accumulated = "".join(full_output)
        yield f"data: {json.dumps({'type': 'response.output_text.done', 'text': accumulated})}\n\n".encode("utf-8")
        yield f"data: {json.dumps({'type': 'response.completed', 'response': {'id': resp_id, 'status': 'completed', 'output_text': accumulated}})}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"

    async def generate_chat_completions_sse_stream(self, prompt: str, model: str = None, on_chunk=None) -> AsyncGenerator[bytes, None]:
        """표준 OpenAI (/v1/chat/completions) 규격 SSE 스트림 생성기"""
        full_output = []
        async for chunk in self.stream_agy_process(prompt, model):
            full_output.append(chunk)
            if on_chunk:
                on_chunk(chunk.encode("utf-8"))
            data = {"choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]}
            yield f"data: {json.dumps(data)}\n\n".encode("utf-8")

        stop_data = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(stop_data)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
