import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from dotenv import load_dotenv

# Load configuration from .env if present
load_dotenv()

app = FastAPI(title="TierBridge")

# [Session Usage Tracker]
# Accumulates token consumption across all proxied requests in this server session.
usage_tracker = {
    "total_requests": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "history": []  # Per-request breakdown: model, effort, tokens
}

# [Environment Configuration]
ENTERPRISE_API_URL = os.getenv(
    "ENTERPRISE_API_URL", 
    "https://chatgpt.com/backend-api/codex/responses"
)

# Activate local mock testing mode when MOCK_TEST_MODE is true or endpoint is set to mock/test
MOCK_MODE = os.getenv("MOCK_TEST_MODE", "false").lower() == "true" or ENTERPRISE_API_URL in ("mock", "test")

# If running in mock mode, route requests to local mock endpoints (Port 18080)
if MOCK_MODE:
    print("[Info] Running in MOCK test mode. Rewriting ENTERPRISE_API_URL to local mock endpoint.")
    REAL_ENTERPRISE_API_URL = ENTERPRISE_API_URL
    ENTERPRISE_API_URL = "http://localhost:18080/mock/enterprise/chat/completions"

def get_latest_enterprise_token() -> str:
    """
    Dynamically harvest the latest ChatGPT access_token from ~/.codex/auth.json or auth.json.bak
    so we don't hit 401 Unauthorized scope issues.
    """
    paths = [
        os.path.expanduser("~/.codex/auth.json"),
        os.path.expanduser("~/.codex/auth.json.bak")
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                tokens = data.get("tokens") or {}
                access_token = tokens.get("access_token")
                if access_token:
                    if not access_token.startswith("Bearer "):
                        return f"Bearer {access_token}"
                    return access_token
            except Exception as e:
                print(f"[Warning] Failed to harvest token from {path}: {e}")
    return ""


def get_latest_enterprise_account_id() -> str:
    """Return the active enterprise account id without exposing authentication data."""
    paths = [
        os.path.expanduser("~/.codex/auth.json"),
        os.path.expanduser("~/.codex/auth.json.bak")
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                account_id = (data.get("tokens") or {}).get("account_id")
                if account_id:
                    return account_id
            except Exception as e:
                print(f"[Warning] Failed to read account id from {path}: {e}")
    return ""

async def estimate_model_and_effort(user_prompt: str, token: str, orig_headers: dict) -> str:
    """
    Evaluates the model tier and reasoning effort level concurrently
    by querying the enterprise gpt-5.4-mini model via the responses API,
    replicating security headers.
    """
    # If there is no token, use the cost-safe default rather than an expensive tier.
    if not token:
        print("[Warning] No Authorization token provided. Falling back to LUNA:MEDIUM.")
        return "LUNA:MEDIUM"

    try:
        # Replicate CLI's original headers with denylist filtering to bypass Cloudflare
        headers = {}
        denylist = (
            "host", "content-length", "content-type", 
            "connection", "keep-alive", "transfer-encoding",
            "accept-encoding", "origin", "referer", "authorization"
        )
        for k, v in orig_headers.items():
            if k.lower() in denylist:
                continue
            headers[k] = v
            
        headers["Authorization"] = token
        headers["Content-Type"] = "application/json"
        headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        # Preserve a stable response shape for the classifier and avoid accidental tool/metadata leakage.
        headers["Accept"] = "text/event-stream"
        if not any(k.lower() == "chatgpt-account-id" for k in headers):
            account_id = get_latest_enterprise_account_id()
            if account_id:
                headers["chatgpt-account-id"] = account_id

        debug_headers = {
            "authorization_present": bool(headers.get("Authorization")),
            "accept": headers.get("Accept"),
            "content_type": headers.get("Content-Type"),
            "user_agent": headers.get("User-Agent"),
            "chatgpt_account_id_present": any(k.lower() == "chatgpt-account-id" for k in headers),
        }
        print(f"[Debug] Classifier request headers: {json.dumps(debug_headers, ensure_ascii=False)}")

        async with httpx.AsyncClient() as client:
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

            print(f"[Debug] Classifier request payload model: {payload['model']}")

            # print(f"[DEBUG Classifier Request Headers] {json.dumps(headers, indent=2)}")
            
            verdict_text = ""
            async with client.stream("POST", ENTERPRISE_API_URL, headers=headers, json=payload, timeout=8.0) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    safe_error = error_body.decode("utf-8", errors="replace")[:500]
                    print(
                        f"[Warning] Classifier request returned HTTP {response.status_code}. "
                        f"Body preview: {safe_error}"
                    )
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            continue
                        try:
                            data_json = json.loads(data_str)
                            if data_json.get("choices"):
                                choice = data_json[0] if isinstance(data_json, list) else data_json.get("choices", [{}])[0]
                                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                                content = message.get("content", "")
                                if isinstance(content, str) and content.strip():
                                    verdict_text += content
                                    continue
                            # Extract completed text from done event
                            if data_json.get("type") == "response.output_text.done":
                                verdict_text = data_json.get("text", "")
                            # Fallback delta accumulation
                            elif data_json.get("type") == "response.output_text.delta":
                                delta_text = data_json.get("delta")
                                if isinstance(delta_text, str):
                                    verdict_text += delta_text
                        except Exception:
                            pass
            
            verdict = verdict_text.strip().upper()
            # print(f"[DEBUG Classifier Raw Verdict Output] {verdict}")

            # Validation and standard tier mapping
            valid_tiers = ["MINI", "LUNA:LOW", "LUNA:MEDIUM", "TERRA:MEDIUM", "TERRA:HIGH", "TERRA:EXTRA_HIGH", "TERRA:MAX"]
            for tier in valid_tiers:
                if tier in verdict:
                    return tier
            return "LUNA:MEDIUM"  # Default fallback mapping
            
    except Exception as e:
        print(f"[Warning] Effort estimation failed, safely falling back to LUNA:MEDIUM: {e}")
        return "LUNA:MEDIUM"

@app.post("/api/pull")
async def mock_ollama_pull(request: Request):
    """
    Mock endpoint satisfying Ollama model pulling checks.
    """
    print("[Mock Ollama] Pulling model request received.")
    async def stream_progress():
        status_updates = [
            {"status": "pulling manifest"},
            {"status": "downloading", "completed": 100, "total": 100},
            {"status": "success"}
        ]
        for update in status_updates:
            yield (json.dumps(update) + "\n").encode("utf-8")
    return StreamingResponse(stream_progress(), media_type="application/x-ndjson")

@app.get("/")
async def ollama_root():
    """
    Mock root endpoint - Codex CLI checks GET / to verify Ollama server is alive.
    Real Ollama returns 'Ollama is running' as plain text.
    """
    return PlainTextResponse("Ollama is running")

@app.get("/api/version")
async def ollama_version():
    """
    Mock /api/version endpoint - Codex CLI checks this to detect Ollama version.
    """
    return {"version": "0.13.4"}

@app.get("/api/tags")
@app.get("/v1/api/tags")
async def mock_ollama_tags():
    """
    Mock endpoint satisfying Ollama tags check.
    """
    return {
        "models": [
            {
                "name": "gpt-5.4",
                "model": "gpt-5.4",
                "size": 12000000000,
                "digest": "sha256:mock"
            }
        ]
    }

@app.get("/v1/models")
@app.get("/v1/v1/models")
async def get_models():
    """
    Mock endpoint satisfying the LM Studio/Ollama discovery check.
    """
    return {
        "object": "list",
        "data": [
            {"id": "gpt-5.4-mini", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-luna", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-terra", "object": "model", "owned_by": "openai"}
        ]
    }

def _parse_and_track_usage(buffer: bytes, model: str, decision: str, effort: str):
    """
    Parses the buffered SSE response stream to extract token usage from
    'response.completed' events, then accumulates into usage_tracker.
    """
    try:
        text = buffer.decode("utf-8", errors="ignore")
        input_tokens = 0
        output_tokens = 0
        for line in text.splitlines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
                # response.completed carries the final usage summary
                if event.get("type") == "response.completed":
                    usage = event.get("response", {}).get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                # Fallback: standard OpenAI chat completions usage field
                elif "usage" in event and event["usage"]:
                    input_tokens = event["usage"].get("prompt_tokens", 0)
                    output_tokens = event["usage"].get("completion_tokens", 0)
            except Exception:
                continue
        if input_tokens or output_tokens:
            usage_tracker["total_requests"] += 1
            usage_tracker["total_input_tokens"] += input_tokens
            usage_tracker["total_output_tokens"] += output_tokens
            usage_tracker["history"].append({
                "model": model,
                "decision": decision,
                "effort": effort,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })
            print(f"➔ [USAGE] {decision} ({model}) | input={input_tokens} output={output_tokens} tokens")
    except Exception as e:
        print(f"[Warning] Failed to parse usage from stream: {e}")


@app.get("/usage")
async def get_usage():
    """
    Returns accumulated token usage for the current proxy server session.
    Use: curl http://localhost:18080/usage
    """
    total_in = usage_tracker["total_input_tokens"]
    total_out = usage_tracker["total_output_tokens"]
    return {
        "session_summary": {
            "total_requests": usage_tracker["total_requests"],
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_in + total_out,
        },
        "per_request_history": usage_tracker["history"],
    }


@app.post("/v1/chat/completions")
@app.post("/v1/v1/chat/completions")
@app.post("/v1/responses")
@app.post("/v1/v1/responses")
async def route_harness(request: Request):
    body = await request.json()
    # print(f"\n[DEBUG] Incoming Request Body:\n{json.dumps(body, indent=2)}\n")
    orig_headers = dict(request.headers)
    
    # Locate the authorization header in a case-insensitive manner
    enterprise_token = None
    for key, value in orig_headers.items():
        if key.lower() == "authorization":
            enterprise_token = value
            break

    # If no token is provided in the headers (like under --oss mode),
    # dynamically harvest the token from the user's ~/.codex/auth.json file.
    if not enterprise_token:
        enterprise_token = get_latest_enterprise_token()
        if enterprise_token:
            print(f"[Info] Dynamically harvested active token from auth.json: {enterprise_token[:25]}...")
        else:
            print("[Warning] No active token found in auth.json or headers.")

    # 1. Extract the latest user prompt from either supported request shape.
    last_prompt = ""
    inputs = body.get("input", [])
    if inputs:
        # Find the last message content
        last_msg = inputs[-1]
        content = last_msg.get("content", [])
        if isinstance(content, list):
            text_parts = [
                part.get("text", "") 
                for part in content 
                if isinstance(part, dict) and part.get("type") == "input_text"
            ]
            last_prompt = " ".join(text_parts)
        else:
            last_prompt = str(content)
    else:
        messages = body.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message.get("content", "")
            if isinstance(content, list):
                last_prompt = " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
            else:
                last_prompt = str(content)
            break

    # 2. Dynamic estimation of model and reasoning effort using gpt-5.4-mini
    decision = await estimate_model_and_effort(last_prompt, enterprise_token, orig_headers)
    print(f"➔ [DECISION] 추정된 등급: {decision}")

    # 3. Payload conversion (Model Mapping to Real Physical ChatGPT IDs)
    if decision == "MINI":
        body["model"] = "gpt-5.4-mini"
    elif decision.startswith("LUNA"):
        body["model"] = "gpt-5.6-luna"
    elif decision.startswith("TERRA"):
        body["model"] = "gpt-5.6-terra"

    decision_to_effort = {
        "MINI": "low",
        "LUNA:LOW": "low",
        "LUNA:MEDIUM": "medium",
        "TERRA:MEDIUM": "medium",
        "TERRA:HIGH": "high",
        "TERRA:EXTRA_HIGH": "extra_high",
        "TERRA:MAX": "max",
    }
    # Translate top-level reasoning_effort into nested reasoning schema for ChatGPT Enterprise compatibility
    effort = decision_to_effort.get(decision)
    if "reasoning_effort" in body:
        del body["reasoning_effort"]
    
    if effort and effort != "none":
        body["reasoning"] = {"effort": effort}
    else:
        # If no reasoning effort is chosen or it is 'none', remove reasoning configuration
        if "reasoning" in body:
            del body["reasoning"]

    # Force store to false to pass ChatGPT backend validation.
    body["store"] = False

    # Replicate original headers for forwarding, filtering out sensitive/protocol headers
    headers = {}
    denylist = (
        "host", "content-length", "content-type", 
        "connection", "keep-alive", "transfer-encoding",
        "accept-encoding", "origin", "referer", "authorization"
    )
    for k, v in orig_headers.items():
        if k.lower() in denylist:
            continue
        headers[k] = v

    if enterprise_token:
        headers["Authorization"] = enterprise_token
    if not any(k.lower() == "chatgpt-account-id" for k in headers):
        account_id = get_latest_enterprise_account_id()
        if account_id:
            headers["chatgpt-account-id"] = account_id
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # print(f"[DEBUG Forwarding Request Headers] {json.dumps(headers, indent=2)}")
    # Determine dynamic target upstream URL based on incoming path (chat/completions vs responses)
    incoming_path = request.url.path
    suffix = "/backend-api/codex/responses" if "responses" in incoming_path else "/backend-api/codex/chat/completions"
    
    if MOCK_MODE:
        mock_suffix = "/v1/responses" if "responses" in incoming_path else "/v1/chat/completions"
        target_url = f"http://localhost:18080/mock/enterprise{mock_suffix}"
    else:
        from urllib.parse import urlparse
        parsed_url = urlparse(ENTERPRISE_API_URL)
        base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        target_url = f"{base_domain}{suffix}"

    # 4. SSE Stream data forwarding pipeline (with token usage tracking)
    async def stream_generator():
        buffer = b""
        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                async with client.stream("POST", target_url, json=body, headers=headers, timeout=180.0) as upstream_res:
                    if upstream_res.status_code != 200:
                        error_body = await upstream_res.aread()
                        print(f"[Warning] Upstream connection error: Status {upstream_res.status_code}, Body: {error_body.decode('utf-8', errors='ignore')}")
                    async for chunk in upstream_res.aiter_bytes():
                        buffer += chunk
                        yield chunk
                # Parse usage from buffered SSE after stream ends
                _parse_and_track_usage(buffer, body.get("model", "unknown"), decision, effort)
            except Exception as e:
                print(f"[Error] Error during stream forwarding: {e}")
                err_msg = json.dumps({
                    "error": {
                        "message": f"Proxy stream connection error: {str(e)}",
                        "type": "proxy_error"
                    }
                })
                yield f"data: {err_msg}\n\n".encode("utf-8")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


# ==========================================
# MOCK ENDPOINTS (Enabled when MOCK_MODE is True)
# ==========================================

@app.post("/mock/enterprise/chat/completions")
@app.post("/mock/enterprise/responses")
@app.post("/mock/enterprise/v1/chat/completions")
@app.post("/mock/enterprise/v1/responses")
async def mock_enterprise_completions(request: Request):
    """
    Mock endpoint simulating the Codex Enterprise API.
    Handles classifier prompts (via gpt-5.4-mini) and redirected model completions.
    """
    orig_headers = dict(request.headers)
    auth_header = orig_headers.get("authorization", "")
    
    body = await request.json()
    model = body.get("model", "")
    messages = body.get("messages", [])
    last_prompt = messages[-1]["content"] if messages else ""
    
    # 1. Check if this is a classifier call
    is_classification = False
    for msg in messages:
        if msg.get("role") == "system" and "사내 크레딧 아키텍처 라우터" in msg.get("content", ""):
            is_classification = True
            break
            
    if is_classification:
        # Determine classification tier based on prompt keywords
        # Test 1: 단순 오타 수정 -> MINI
        # Test 2: 단순 알고리즘 질문 -> LUNA:LOW
        # Test 3: 성능 최적화 디버깅 -> TERRA:EXTRA_HIGH
        # Test 4: 대규모 동시성 분산 락(Lock) 이슈 질문 -> TERRA:MAX
        verdict = "LUNA:MEDIUM"
        
        if "알고리즘" in last_prompt or "simple" in last_prompt or "단순" in last_prompt:
            # We want to distinguish simple sorting from simple typo
            if "오타" in last_prompt or "명령어" in last_prompt:
                verdict = "MINI"
            else:
                verdict = "LUNA:LOW"
        elif "최적화" in last_prompt or "tuning" in last_prompt or "메모리 누수" in last_prompt:
            verdict = "TERRA:EXTRA_HIGH"
        elif "분산 락" in last_prompt or "교착상태" in last_prompt or "deadlock" in last_prompt or "동시성" in last_prompt:
            verdict = "TERRA:MAX"
        elif "오타" in last_prompt or "grammar" in last_prompt or "오타 수정" in last_prompt:
            verdict = "MINI"
            
        print(f"[Mock Classifier] Classifier received token: '{auth_header[:25]}...'")
        print(f"[Mock Classifier] Routing verdict for prompt '{last_prompt[:30]}...' -> {verdict}")
        
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": verdict
                    },
                    "finish_reason": "stop",
                    "index": 0
                }
            ]
        }
    
    # 2. Otherwise, treat as streaming chat completion request
    effort = body.get("reasoning_effort", "none")
    print(f"[Mock Enterprise API] Streaming request received. Model: {model}, Effort: {effort}")
    print(f"[Mock Enterprise API] Authorization Token: '{auth_header[:25]}...'")

    async def mock_stream():
        response_text = (
            f"이것은 {model} (추론 레벨: {effort})의 답변입니다. "
            f"질의하신 내용 '{last_prompt[:30]}...'에 대한 심층적 코딩 분석 결과입니다."
        )
        
        # 1. Emit response.created event (Unified block)
        created_data = {"id": "mock-resp", "object": "response", "status": "in_progress"}
        yield f"event: response.created\ndata: {json.dumps(created_data)}\n\n".encode("utf-8")
        
        # 2. Emit text delta events (Unified block per character)
        for char in response_text:
            data_obj = {
                "id": "mock-resp",
                "object": "response.content_part.delta",
                "index": 0,
                "delta": {
                    "type": "text",
                    "text": char
                }
            }
            yield f"event: response.content_part.delta\ndata: {json.dumps(data_obj)}\n\n".encode("utf-8")
        
        # 3. Emit response.completed event containing the full accumulated output
        completed_data = {
            "id": "mock-resp",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "item_123",
                    "object": "response.output_item",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": response_text
                        }
                    ]
                }
            ]
        }
        yield f"event: response.completed\ndata: {json.dumps(completed_data)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        
    return StreamingResponse(mock_stream(), media_type="text/event-stream")
