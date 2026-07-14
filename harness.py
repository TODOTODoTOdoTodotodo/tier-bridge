import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from dotenv import load_dotenv

# TierBridge 패키지 임포트
from tierbridge.models import UnifiedRequest
from tierbridge.adapters.factory import AdapterFactory
from tierbridge.stream_transpiler import StreamTranspiler
from tierbridge.router import Router
from tierbridge.auth_manager import AuthManager
from tierbridge.usage_tracker import UsageTracker

load_dotenv()

app = FastAPI(title="TierBridge")

# 싱글톤 세션 사용량 트래커 초기화
global_tracker = UsageTracker()

# 환경 변수 및 설정 로드
ENTERPRISE_API_URL = os.getenv(
    "ENTERPRISE_API_URL", 
    "https://chatgpt.com/backend-api/codex/responses"
)
MOCK_MODE = os.getenv("MOCK_TEST_MODE", "false").lower() == "true" or ENTERPRISE_API_URL in ("mock", "test")
print(f"[Debug System Config] MOCK_TEST_MODE: {os.getenv('MOCK_TEST_MODE')}, ENTERPRISE_API_URL: {ENTERPRISE_API_URL}, Final MOCK_MODE: {MOCK_MODE}")

# Mock 모드 활성화 시 로컬 모크 엔드포인트로 우회
if MOCK_MODE:
    print("[Info] Running in MOCK test mode. Rewriting ENTERPRISE_API_URL to local mock endpoint.")
    ENTERPRISE_API_URL = "http://localhost:18080/mock/enterprise/chat/completions"

def get_latest_enterprise_token() -> str:
    """ ~/.codex/auth.json 에서 최신 ChatGPT access_token 로드 """
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
                print(f"[Warning] Failed to harvest token: {e}")
    return ""

def get_latest_enterprise_account_id() -> str:
    """ auth.json 에서 active account_id 로드 """
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
                print(f"[Warning] Failed to read account id: {e}")
    return ""

# ==========================================
# 에이전트 CLI 구동용 Mock/Discovery 엔드포인트
# ==========================================

@app.get("/")
async def ollama_root():
    return PlainTextResponse("Ollama is running")

@app.get("/api/version")
async def ollama_version():
    return {"version": "0.13.4"}

@app.get("/api/tags")
@app.get("/v1/api/tags")
async def mock_ollama_tags():
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
    return {
        "object": "list",
        "data": [
            {"id": "gpt-5.4-mini", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-luna", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-terra", "object": "model", "owned_by": "openai"}
        ]
    }

@app.post("/api/pull")
async def mock_ollama_pull(request: Request):
    async def stream_progress():
        status_updates = [
            {"status": "pulling manifest"},
            {"status": "downloading", "completed": 100, "total": 100},
            {"status": "success"}
        ]
        for update in status_updates:
            yield (json.dumps(update) + "\n").encode("utf-8")
    return StreamingResponse(stream_progress(), media_type="application/x-ndjson")

@app.get("/usage")
async def get_usage():
    """ 실시간으로 세션 누적 사용량 및 예상 비용(USD) 조회 """
    return global_tracker.get_summary()

# ==========================================
# 핵심 라우팅 하네스 엔드포인트
# ==========================================

@app.post("/v1/chat/completions")
@app.post("/v1/v1/chat/completions")
@app.post("/v1/responses")
@app.post("/v1/v1/responses")
async def route_harness(request: Request):
    raw_body = await request.json()
    orig_headers = dict(request.headers)
    incoming_path = request.url.path

    # 1. 인바운드 소스 프로토콜 판별 (경로 및 페이로드 스펙 기준)
    source_vendor = "openai"
    if "messages" in incoming_path:
        source_vendor = "anthropic"
    elif "contents" in raw_body:
        source_vendor = "gemini"

    # 2. 어댑터 팩토리로부터 해당 에이전트용 소스 어댑터 생성
    source_adapter = AdapterFactory.get_adapter(source_vendor)
    
    # 3. 인바운드 요청을 정규화 메시지 포맷으로 파싱
    unified_req = source_adapter.to_unified_request(raw_body)

    # 4. 엔터프라이즈 자격증명 탐지
    enterprise_token = None
    for k, v in orig_headers.items():
        if k.lower() == "authorization":
            enterprise_token = v
            break
    if not enterprise_token:
        enterprise_token = get_latest_enterprise_token()

    # 5. 분류기를 이용한 난이도 의사결정 (gpt-5.4-mini 호출)
    decision, target_model, effort = await Router.classify_request(
        unified_request=unified_req,
        auth_token=enterprise_token,
        enterprise_api_url=ENTERPRISE_API_URL,
        account_id=get_latest_enterprise_account_id()
    )

    # 6. 타겟 백엔드 벤더 매핑
    target_vendor = "openai"
    if "claude" in target_model:
        target_vendor = "anthropic"
    elif "gemini" in target_model:
        target_vendor = "gemini"

    # 7. 타겟 어댑터 및 자격증명 스왑 해결
    target_adapter = AdapterFactory.get_adapter(target_vendor)
    target_headers = AuthManager.resolve_auth_headers(orig_headers, source_vendor, target_vendor)

    # 만약 타겟이 엔터프라이즈 ChatGPT API(OpenAI 규격)인 경우 필요한 보조 헤더 추가
    if target_vendor == "openai":
        target_headers["Content-Type"] = "application/json"
        target_headers["Accept"] = "text/event-stream"
        target_headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        if not any(k.lower() == "chatgpt-account-id" for k in target_headers):
            account_id = get_latest_enterprise_account_id()
            if account_id:
                target_headers["chatgpt-account-id"] = account_id

    # 8. 정규화 요청으로부터 최종 백엔드 전송 페이로드 구성
    # 3-Tier에 기반한 모델 정보 및 추론 수준(reasoning_effort) 적용
    unified_req.model = target_model
    
    final_payload = target_adapter.from_unified_request(unified_req)
    
    # ChatGPT Enterprise API 특화 파라미터 적용 (reasoning.effort 포맷)
    if target_vendor == "openai":
        if "reasoning_effort" in final_payload:
            del final_payload["reasoning_effort"]
        if effort and effort != "low":
            final_payload["reasoning"] = {"effort": effort}
        else:
            if "reasoning" in final_payload:
                del final_payload["reasoning"]
        final_payload["store"] = False

    # 9. 동적 타겟 업스트림 경로 수립
    suffix = "/backend-api/codex/responses" if "responses" in incoming_path else "/backend-api/codex/chat/completions"
    if MOCK_MODE:
        mock_suffix = "/v1/responses" if "responses" in incoming_path else "/v1/chat/completions"
        upstream_url = f"http://localhost:18080/mock/enterprise{mock_suffix}"
    else:
        from urllib.parse import urlparse
        parsed_url = urlparse(ENTERPRISE_API_URL)
        base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        upstream_url = f"{base_domain}{suffix}"

    # 10. 스트리밍 비동기 포워딩 및 실시간 트랜스파일링 파이프라인
    if unified_req.stream:
        async def stream_generator():
            accumulated_buffer = b""
            
            def append_raw(chunk_bytes: bytes):
                nonlocal accumulated_buffer
                accumulated_buffer += chunk_bytes
                
            async with httpx.AsyncClient(timeout=180.0) as client:
                try:
                    # 백엔드 비동기 스트림 시작
                    async with client.stream("POST", upstream_url, json=final_payload, headers=target_headers, timeout=180.0) as upstream_res:
                        if upstream_res.status_code != 200:
                            error_body = await upstream_res.aread()
                            print(f"[Warning] Upstream API Error Status: {upstream_res.status_code}, Body: {error_body.decode('utf-8', errors='ignore')}")
                            upstream_res.raise_for_status()

                        # 실시간 트랜스파일링을 물려서 데이터 방출 (원본 수집 콜백 전달)
                        raw_generator = upstream_res.aiter_bytes()
                        async for transpiled_chunk in StreamTranspiler.transpile_stream(raw_generator, source_adapter, target_adapter, on_raw_chunk=append_raw):
                            yield transpiled_chunk
                            
                    # 스트림이 모두 종료된 후 백그라운드 사용량 파싱 및 누적
                    global_tracker.parse_and_track_from_buffer(accumulated_buffer, target_model, decision)
                except Exception as e:
                    print(f"[Error] Stream routing exception: {e}")
                    err_msg = json.dumps({"error": {"message": f"Proxy routing exception: {str(e)}", "type": "proxy_error"}})
                    yield f"data: {err_msg}\n\n".encode("utf-8")

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    
    # 11. 논스트림(Non-streaming) 동기 포워딩 파이프라인
    else:
        try:
            res = await target_adapter.send_request(final_payload, target_headers, upstream_url)
            if res.status_code == 200:
                # 사용량 추적기 로깅
                res_data = res.json()
                usage = res_data.get("usage", {})
                in_tok = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)
                if in_tok or out_tok:
                    global_tracker.track_request(target_model, decision, in_tok, out_tok)
            return res
        except Exception as e:
            return PlainTextResponse(f"Proxy connection failed: {e}", status_code=500)

# ==========================================
# MOCK ENTERPRISE API (테스트 자동화용)
# ==========================================

@app.post("/mock/enterprise/chat/completions")
@app.post("/mock/enterprise/responses")
@app.post("/mock/enterprise/v1/chat/completions")
@app.post("/mock/enterprise/v1/responses")
async def mock_enterprise_completions(request: Request):
    orig_headers = dict(request.headers)
    auth_header = orig_headers.get("authorization", "")
    
    body = await request.json()
    model = body.get("model", "")
    messages = body.get("messages", [])
    last_prompt = messages[-1]["content"] if messages else ""
    
    # 분류기 호출 식별
    is_classification = False
    for msg in messages:
        if msg.get("role") == "system" and "비용 절감용 라우터" in msg.get("content", ""):
            is_classification = True
            break
            
    if is_classification:
        verdict = "LUNA:MEDIUM"
        if "알고리즘" in last_prompt or "simple" in last_prompt or "단순" in last_prompt:
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
            
        print(f"[Mock Classifier] Routing verdict for prompt -> {verdict}")
        
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
    
    # 2. 일반 스트리밍 가짜 응답 생성
    effort = body.get("reasoning", {}).get("effort", "none")
    print(f"[Mock Enterprise API] Streaming Model: {model}, Effort: {effort}")

    async def mock_stream():
        response_text = (
            f"이것은 {model} (추론 레벨: {effort})의 답변입니다. "
            f"질의하신 내용 '{last_prompt[:30]}...'에 대한 심층적 코딩 분석 결과입니다."
        )
        
        # response.created
        created_data = {"id": "mock-resp", "object": "response", "status": "in_progress"}
        yield f"event: response.created\ndata: {json.dumps(created_data)}\n\n".encode("utf-8")
        
        # text deltas
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
        
        # response.completed
        completed_data = {
            "id": "mock-resp",
            "object": "response",
            "status": "completed",
            "response": {
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 80
                }
            }
        }
        yield f"event: response.completed\ndata: {json.dumps(completed_data)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
        
    return StreamingResponse(mock_stream(), media_type="text/event-stream")
