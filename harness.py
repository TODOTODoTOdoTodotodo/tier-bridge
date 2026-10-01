import os
import json
import re
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, PlainTextResponse, Response
from dotenv import load_dotenv

# TierBridge 패키지 임포트
from tierbridge.models import UnifiedRequest, Message
from tierbridge.adapters.factory import AdapterFactory
from tierbridge.stream_transpiler import StreamTranspiler
from tierbridge.router import Router
from tierbridge.auth_manager import AuthManager
from tierbridge.usage_tracker import UsageTracker
from tierbridge.memory_prefetcher import MemoryPrefetcher
from tierbridge.memory_handler import MemoryHandler
from tierbridge.system_directive import SystemDirective

import logging

# 시스템 로깅 레벨 WARNING 상향 설정 (잡다한 INFO 로그 차단)
logging.basicConfig(level=logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("harness")

from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="TierBridge")

# 브라우저 대시보드 3초 라이브 오토싱크 및 AJAX 요청용 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    async def run_periodic_pricing_sync():
        while True:
            try:
                try:
                    from src.tierbridge.official_pricing_crawler import OfficialPricingCrawler
                except ImportError:
                    from tierbridge.official_pricing_crawler import OfficialPricingCrawler
                OfficialPricingCrawler.sync_prices(force=False)
            except Exception as e:
                log.error(f"Error in periodic pricing sync: {e}")
            await asyncio.sleep(21600)  # 6시간 주기 자동 갱신

    asyncio.create_task(run_periodic_pricing_sync())

# 싱글톤 세션 사용량 트래커 초기화
global_tracker = UsageTracker()

# 환경 변수 및 설정 로드
ENTERPRISE_API_URL = os.getenv(
    "ENTERPRISE_API_URL", 
    "https://chatgpt.com/backend-api/codex/responses"
)
MOCK_MODE = os.getenv("MOCK_TEST_MODE", "false").lower() == "true" or ENTERPRISE_API_URL in ("mock", "test")
ROUTING_MODE = os.getenv("ROUTING_MODE", "standard").lower()
HIGH_POWER_MODE = os.getenv("HIGH_POWER_MODE", "false").lower() == "true" or ROUTING_MODE in ("high_power", "high", "power")
UPSTREAM_PROVIDER = os.getenv("UPSTREAM_PROVIDER", "auto").lower()  # "auto" (auto-failover), "agy", "gemini", "chatgpt"
AGY_MODEL = os.getenv("AGY_MODEL", "gemini-3.8-flash-high")

# Mock 모드 활성화 시 로컬 모크 엔드포인트로 우회
if MOCK_MODE:
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
            {"id": "gpt-6.1-sol", "object": "model", "owned_by": "openai"},
            {"id": "gpt-6-luna", "object": "model", "owned_by": "openai"},
            {"id": "gpt-6-sol", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.4-mini", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-luna", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-terra", "object": "model", "owned_by": "openai"},
            {"id": "gpt-5.6-sol", "object": "model", "owned_by": "openai"},
            {"id": "4tier", "object": "model", "owned_by": "openai"},
            {"id": "super", "object": "model", "owned_by": "openai"},
            {"id": "gemini-3.8-flash-high", "object": "model", "owned_by": "google"},
            {"id": "gemini-3.8-flash-medium", "object": "model", "owned_by": "google"},
            {"id": "gemini-3.8-flash-low", "object": "model", "owned_by": "google"},
            {"id": "agy", "object": "model", "owned_by": "google"},
            {"id": "gemini", "object": "model", "owned_by": "google"}
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

from src.tierbridge.healing_engine import HealingEngine

@app.get("/v1/models/healing-status")
async def get_healing_status():
    """ 힐링 모듈 상태, 신규 모델 발견 여부 및 비용 비교표 조회 """
    return HealingEngine.get_healing_status()

@app.post("/v1/models/heal")
async def apply_healing():
    """ 신규 저비용/고출력 모델 스냅샷을 핫패치 릴리즈 적용 """
    res = HealingEngine.apply_healing()
    msg = f"➔ [HEALING] Hot-patch applied | active_version_id={res.get('active_version_id')} | message={res.get('message')}"
    print(msg, flush=True)
    log.warning(msg)
    return res

@app.post("/v1/models/version/switch")
async def switch_model_version(request: Request):
    """ 특정 모델 버전(e.g., v1.0.0, latest)으로 라우팅 롤백/복원 """
    try:
        body = await request.json()
        version_id = body.get("version_id", "latest")
    except Exception:
        version_id = "latest"
    res = HealingEngine.switch_version(version_id)
    msg = f"➔ [VERSION_SWITCH] Switched model version | version_id={version_id} | active_version_id={res.get('active_version_id')}"
    print(msg, flush=True)
    log.warning(msg)
    return res

try:
    from src.tierbridge.official_pricing_crawler import OfficialPricingCrawler
except ImportError:
    from tierbridge.official_pricing_crawler import OfficialPricingCrawler

@app.get("/v1/models/pricing")
async def get_official_pricing():
    """ OpenAI 공식 수집 단가표 조회 """
    return OfficialPricingCrawler.load_prices()

@app.post("/v1/models/pricing/sync")
async def sync_official_pricing():
    """ OpenAI 공식 단가 원격 강제 동기화 수행 """
    res = OfficialPricingCrawler.sync_prices(force=True)
    msg = f"➔ [PRICING_SYNC] Official pricing synced | updated_at={res.get('updated_at')} | success={res.get('success')}"
    print(msg, flush=True)
    log.warning(msg)
    return res

@app.get("/v1/classifier/telemetry")
async def get_classifier_telemetry():
    """ 5단계 SOLID 분류 파이프라인 텔레메트리 메트릭 조회 """
    try:
        from src.tierbridge.classifier.pipeline import ClassifierPipeline
    except ImportError:
        from tierbridge.classifier.pipeline import ClassifierPipeline
    return ClassifierPipeline().get_telemetry()

@app.get("/v1/dashboard/stats")
async def get_dashboard_stats():
    env_log = os.environ.get("TIERBRIDGE_LOG_PATH")
    live_log = os.path.expanduser("~/.tierbridge/live/harness.log")
    dev_dir = os.environ.get("TIERBRIDGE_DEV_DIR")
    dev_log = os.path.join(dev_dir, "harness.log") if dev_dir else None
    if env_log and os.path.exists(env_log):
        log_file = env_log
    elif os.path.exists(live_log):
        log_file = live_log
    elif dev_log and os.path.exists(dev_log):
        log_file = dev_log
    elif os.path.exists("harness.log"):
        log_file = "harness.log"
    else:
        log_file = "harness.log"
    records = []
    prompt_history = []
    session_prompts = {}
    
    if os.path.exists(log_file):
        usage_pattern = re.compile(
            r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[USAGE(?::\s*(?P<decision_opt>[^\]]+))?\](?:\s+(?P<decision_legacy>[^\s(]+))?\s+\((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| real_credit=(?P<real_credit>[\d\.]+))?(?: \| balance=(?P<balance>[\d\.]+))?(?: \| loc=(?P<loc>\d+) lines)?(?:\s*\|\s*cost=\$(?P<cost>[\d\.]+) USD)?'
        )
        decision_pattern = re.compile(
            r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[DECISION[^\]]*\] (?P<decision>[^\s]+)(?:\s+\([^)]+\))?(?:\s+\[clf:[^\]]+\])?\s*\|\s*\"(?P<prompt>.*)\"$'
        )
        healing_pattern = re.compile(
            r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?➔ \[(?P<event_type>HEALING|VERSION_SWITCH)\] (?P<details>.*)$'
        )
        healing_history = []
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                h_match = healing_pattern.search(line)
                if h_match:
                    healing_history.append({
                        "timestamp": h_match.group("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "event_type": h_match.group("event_type"),
                        "details": h_match.group("details")
                    })
                    continue
                d_match = decision_pattern.search(line)
                if d_match:
                    d_sid = d_match.group("sid") or "N/A"
                    d_prompt = d_match.group("prompt")
                    prompt_history.append({
                        "timestamp": d_match.group("timestamp"),
                        "sid": d_sid,
                        "decision": d_match.group("decision"),
                        "prompt": d_prompt
                    })
                    if d_sid != "N/A":
                        session_prompts[d_sid] = d_prompt
                    continue
                u_match = usage_pattern.search(line)
                if u_match:
                    ts_str = u_match.group("timestamp")
                    sid_str = u_match.group("sid") or "N/A"
                    date_key = "Unknown Date"
                    month_key = "Unknown Month"
                    if ts_str:
                        try:
                            dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                            date_key = dt.strftime("%Y-%m-%d")
                            month_key = dt.strftime("%Y-%m")
                        except ValueError:
                            pass
                    decision_str = u_match.group("decision_opt") or u_match.group("decision_legacy") or "UNKNOWN"
                    model_val = u_match.group("model")
                    in_tok = int(u_match.group("in_tok"))
                    out_tok = int(u_match.group("out_tok"))
                    loc_val = int(u_match.group("loc")) if u_match.group("loc") else 0
                    cost_str = u_match.group("cost")
                    if cost_str:
                        cost = float(cost_str)
                    else:
                        try:
                            try:
                                from tierbridge.official_pricing_crawler import OfficialPricingCrawler
                            except ImportError:
                                from src.tierbridge.official_pricing_crawler import OfficialPricingCrawler
                            in_p, out_p = OfficialPricingCrawler.get_price(model_val, fallback_in=1.0, fallback_out=3.0)
                        except Exception:
                            in_p, out_p = 1.0, 3.0
                        cost = (in_tok / 1_000_000.0) * in_p + (out_tok / 1_000_000.0) * out_p
                    real_credit_val = float(u_match.group("real_credit")) if u_match.group("real_credit") else None
                    balance_val = float(u_match.group("balance")) if u_match.group("balance") else None
                    
                    associated_prompt = ""
                    if sid_str != "N/A" and sid_str in session_prompts:
                        associated_prompt = session_prompts[sid_str]
                    elif prompt_history:
                        for p in reversed(prompt_history):
                            if sid_str != "N/A" and p["sid"] == sid_str:
                                associated_prompt = p["prompt"]
                                break
                        if not associated_prompt and sid_str == "N/A":
                            associated_prompt = prompt_history[-1]["prompt"]
                            if prompt_history[-1]["sid"] != "N/A":
                                sid_str = prompt_history[-1]["sid"]
                        elif not associated_prompt:
                            associated_prompt = prompt_history[-1]["prompt"]

                    if sid_str == "N/A" and associated_prompt:
                        import hashlib
                        prompt_hash = hashlib.md5(associated_prompt.encode("utf-8")).hexdigest()[:8]
                        sid_str = f"sess_{prompt_hash}"
                    elif sid_str == "N/A":
                        sid_str = "sess_legacy"

                    records.append({
                        "timestamp": ts_str or "N/A",
                        "date": date_key,
                        "month": month_key,
                        "session_id": sid_str,
                        "decision": decision_str,
                        "model": u_match.group("model"),
                        "prompt": associated_prompt,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total_tokens": in_tok + out_tok,
                        "loc": loc_val,
                        "cost": cost,
                        "real_credit": real_credit_val,
                        "balance": balance_val
                    })

    try:
        try:
            from tierbridge.credit_interceptor import interceptor
        except ImportError:
            from src.tierbridge.credit_interceptor import interceptor
        ent_balance = await interceptor.fetch_enterprise_usage()
    except Exception:
        ent_balance = None

    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        mem_stats = MemoryHandler.get_memory_stats()
    except Exception:
        mem_stats = {"total_memories": 0, "total_tags": 0, "code_modified_count": 0, "structured_rate": 100.0}

    try:
        try:
            from tierbridge.git_sync_checker import get_git_sync_status
        except ImportError:
            from src.tierbridge.git_sync_checker import get_git_sync_status
        git_sync_data = get_git_sync_status()
    except Exception:
        git_sync_data = {"is_git": False, "needs_pull": False, "behind_count": 0, "pending_commits": []}

    try:
        try:
            from tierbridge.version import get_version_info
        except ImportError:
            from src.tierbridge.version import get_version_info
        app_version_tag = get_version_info().get("tag", "v0.1.1")
    except Exception:
        app_version_tag = "v0.1.1"

    try:
        try:
            from tierbridge.router import Router
        except ImportError:
            from src.tierbridge.router import Router
        clf_status = dict(Router.last_classifier_status)
        if not clf_status.get("last_timestamp"):
            clf_records = [r for r in records if "CLASSIFIER" in r.get("decision", "")]
            if clf_records:
                clf_status["last_used"] = clf_records[-1].get("model", "gpt-reserve")
                clf_status["last_timestamp"] = clf_records[-1].get("timestamp")
        try:
            try:
                from tierbridge.classifier.pipeline import ClassifierPipeline
            except ImportError:
                from src.tierbridge.classifier.pipeline import ClassifierPipeline
            clf_status["telemetry"] = ClassifierPipeline().get_telemetry()
        except Exception:
            clf_status["telemetry"] = {}
    except Exception:
        clf_status = {"primary": "gpt-reserve", "fallback": "gpt-5.6-luna", "last_used": "gpt-reserve", "last_timestamp": None, "telemetry": {}}

    return {
        "app_version": app_version_tag,
        "classifier_status": clf_status,
        "records": records,
        "healing_status": HealingEngine.get_healing_status(),
        "healing_history": list(reversed(healing_history)),
        "enterprise_balance": ent_balance,
        "memory_stats": mem_stats,
        "git_status": git_sync_data
    }

@app.get("/v1/version")
async def get_app_version():
    """ TierBridge 시스템 버전 정보 반환 """
    try:
        try:
            from tierbridge.version import get_version_info
        except ImportError:
            from src.tierbridge.version import get_version_info
        return get_version_info()
    except Exception:
        return {"version": "0.1.1", "tag": "v0.1.1", "name": "TierBridge Core", "release_date": "2026-08-27"}

# ==========================================
# GiyEOK (SUB-MEMORY) DASHBOARD APIS
# ==========================================

@app.get("/v1/dashboard/memories")
async def get_dashboard_memories(limit: int = 50, session_id: Optional[str] = None):
    """ 기억저장소(memory.db)에 적재된 최근 문제-해결 지식 에피소드 목록 조회 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        memories = MemoryHandler.get_recent_memories(limit=limit, session_id=session_id)
        return {"status": "success", "total_count": len(memories), "memories": memories}
    except Exception as e:
        return {"status": "error", "message": str(e), "memories": []}

@app.get("/v1/dashboard/memories/search")
async def search_dashboard_memories(q: str = "", limit: int = 10):
    """ 질의어(키워드/시맨틱) 기반 연관 기억 및 유사도 검색 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        results = MemoryHandler.search_associated_memories(query=q, limit=limit)
        return {"status": "success", "query": q, "results_count": len(results), "results": results}
    except Exception as e:
        return {"status": "error", "message": str(e), "results": []}

@app.get("/v1/dashboard/memories/stats")
async def get_dashboard_memory_stats():
    """ 기억저장소 통계 지표 조회 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        return MemoryHandler.get_memory_stats()
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/v1/dashboard/memories/graph")
async def get_dashboard_memory_graph(limit_nodes: int = 60):
    """ vis-network 렌더링용 nodes & edges 그래프 데이터셋 조회 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        data = MemoryHandler.get_graph_data(limit_nodes=limit_nodes)
        return {"status": "success", **data}
    except Exception as e:
        return {"status": "error", "message": str(e), "nodes": [], "edges": []}

@app.get("/v1/dashboard/memories/top-edges")
async def get_dashboard_top_edges(limit: int = 10):
    """ 가장 높은 가중치를 가진 상위 엣지 및 노드 정보 목록 조회 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        edges = MemoryHandler.get_top_weighted_edges(limit=limit)
        return {"status": "success", "total_count": len(edges), "edges": edges}
    except Exception as e:
        return {"status": "error", "message": str(e), "edges": []}

@app.post("/v1/dashboard/memories/neuralize/{node_id}")
async def neuralize_dashboard_memory(node_id: str):
    """ Neuralizer: 특정 기억 노드를 안전하게 삭제하고 연결된 엣지만 정밀 소각 """
    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        result = MemoryHandler.neuralize_memory(node_id)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e), "node_id": node_id}

# ==========================================
# 핵심 라우팅 하네스 엔드포인트
# ==========================================

@app.post("/v1/chat/completions")
@app.post("/v1/v1/chat/completions")
@app.post("/chat/completions")
@app.post("/api/chat")
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

    # CLI 실행 시점에 요청된 모델 식별 (e.g. gpt-5.6-sol, gpt-5.6-terra, high-power)
    requested_model = raw_body.get("model", "")
    
    # 세션 ID 정밀 추출 (conversation_id, session_id, x-conversation-id 또는 첫 질문 프롬프트 해시 기반 Fallback)
    session_id = ""
    if isinstance(raw_body, dict):
        session_id = (
            raw_body.get("conversation_id")
            or raw_body.get("session_id")
            or raw_body.get("chat_id")
        )
        if not session_id and isinstance(raw_body.get("metadata"), dict):
            session_id = raw_body["metadata"].get("conversation_id") or raw_body["metadata"].get("session_id")

    if not session_id and isinstance(orig_headers, dict):
        for k, v in orig_headers.items():
            k_lower = str(k).lower()
            if k_lower in ("x-conversation-id", "x-session-id", "conversation-id", "session-id", "conversation_id", "session_id", "chat-id"):
                if v and str(v).strip():
                    session_id = str(v).strip()
                    break

    if not session_id and unified_req and unified_req.messages:
        for msg in unified_req.messages:
            if msg.role == "user" and msg.content.strip():
                import hashlib
                prompt_hash = hashlib.md5(msg.content.strip().encode("utf-8")).hexdigest()[:8]
                session_id = f"sess_{prompt_hash}"
                break

    if not session_id and isinstance(raw_body, dict) and raw_body.get("user"):
        session_id = str(raw_body.get("user")).strip()

    if not session_id:
        session_id = "sess_main"

    # 5. 프롬프트 텍스트 및 분류기를 이용한 난이도/라우터 선택
    user_prompt, is_new_user_turn, substep_prompt = Router.extract_user_prompt_and_turn_status(unified_req)
    if not user_prompt:
        user_prompt = str(raw_body.get("instructions", "")) + str(raw_body.get("input", ""))

    # Step 2: 사전 기억 회수 (Pre-fetch Recall, 50ms Strict Timeout Sandbox)
    # 사용자의 신규 턴(is_new_user_turn == True) 인입 시에만 1회 회수하여 내부 서브스텝 중복 주입 및 토큰 낭비 방지
    recalled_context = None
    if is_new_user_turn:
        try:
            recalled_context = await MemoryPrefetcher.fetch_associated_context(user_prompt, current_session_id=session_id)
            if recalled_context:
                if unified_req and hasattr(unified_req, "messages") and unified_req.messages:
                    last_msg = unified_req.messages[-1]
                    if last_msg.role == "user":
                        # OpenAI Prompt Caching 접두사(Prefix) 보존:
                        # messages[0] 시스템 프롬프트를 밀지 않고, 사용자 프롬프트 하단에 RAG 연관 지식 블록 첨부
                        last_msg.content = f"{last_msg.content.strip()}\n\n---\n{recalled_context}"
                    else:
                        # Fallback: 비정형 메시지 구조인 경우 messages[0] 뒤(인덱스 1)에 주입하여 0번 프리픽스 보존
                        insert_idx = 1 if len(unified_req.messages) > 1 else 0
                        unified_req.messages.insert(insert_idx, Message(role="system", content=recalled_context))
        except Exception as e:
            log.debug(f"[RecallHook] Memory prefetch bypassed: {e}")

    decision, target_model, effort = await Router.classify_request(
        unified_request=unified_req,
        auth_token=enterprise_token,
        enterprise_api_url=ENTERPRISE_API_URL,
        account_id=get_latest_enterprise_account_id(),
        requested_model=requested_model,
        session_id=session_id
    )

    # 6. 타겟 백엔드 벤더 매핑
    req_model_lower = str(requested_model or "").lower()
    is_agy_target = (
        UPSTREAM_PROVIDER in ("agy", "gemini")
        or req_model_lower.startswith("gemini")
        or req_model_lower in ("agy", "gemini")
        or "gemini" in str(target_model).lower()
    )

    if is_agy_target:
        target_vendor = "agy"
        if req_model_lower.startswith("gemini-"):
            target_model = requested_model
        else:
            target_model = os.getenv("AGY_MODEL", "gemini-3.8-flash-high")
        decision = "AGY_BRIDGE"
    elif "claude" in target_model:
        target_vendor = "anthropic"
    else:
        target_vendor = "openai"

    # 7. 타겟 어댑터 및 자격증명 스왑 해결
    target_adapter = AdapterFactory.get_adapter(target_vendor)
    
    if target_vendor == "openai":
        # master 브랜치의 안전한 헤더 필터링 & 복제 메커니즘 복원
        target_headers = {}
        denylist = (
            "host", "content-length", "content-type", 
            "connection", "keep-alive", "transfer-encoding",
            "accept-encoding", "origin", "referer", "authorization"
        )
        for k, v in orig_headers.items():
            if k.lower() in denylist:
                continue
            target_headers[k] = v

        if enterprise_token:
            target_headers["Authorization"] = enterprise_token
        if not any(k.lower() == "chatgpt-account-id" for k in target_headers):
            account_id = get_latest_enterprise_account_id()
            if account_id:
                target_headers["chatgpt-account-id"] = account_id
        target_headers["Content-Type"] = "application/json"
        target_headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        target_headers["Accept"] = "text/event-stream"
    else:
        target_headers = AuthManager.resolve_auth_headers(orig_headers, source_vendor, target_vendor)

    # 8. 정규화 요청으로부터 최종 백엔드 전송 페이로드 구성
    # 3-Tier에 기반한 모델 정보 및 추론 수준(reasoning_effort) 적용
    unified_req.model = target_model
    
    # 최종 답변을 3단 마크다운 보고서 규격으로 출력하도록 시스템 가이드라인 투명 주입
    unified_req = SystemDirective.inject_into_unified_request(unified_req)

    final_payload = target_adapter.from_unified_request(unified_req)
    
    # ChatGPT Enterprise API 특화 파라미터 적용 (reasoning.effort 포맷 및 /responses 규격 변환)
    if target_vendor == "openai":
        if "reasoning_effort" in final_payload:
            del final_payload["reasoning_effort"]
        
        # ChatGPT Enterprise API는 'extra_high' 대신 'xhigh'를 사용함
        mapped_effort = "xhigh" if effort == "extra_high" else effort
        if mapped_effort and mapped_effort != "low":
            final_payload["reasoning"] = {"effort": mapped_effort}
        else:
            if "reasoning" in final_payload:
                del final_payload["reasoning"]
        final_payload["store"] = False

        # WAF 403 Forbidden을 회피하기 위해 /responses API용 payload 변환 수행
        if (not MOCK_MODE or "responses" in incoming_path):
            if "input" in raw_body:
                # 원본 요청에 이미 input 규격이 있었던 경우 원형 그대로 복원 (이전 대화의 output_text 파괴 방지)
                final_payload["input"] = raw_body["input"]
                if "instructions" in raw_body:
                    final_payload["instructions"] = raw_body["instructions"]
            elif ("messages" in final_payload) and ("input" not in final_payload):
                # OpenAI completions 규격으로 들어온 요청을 responses 규격으로 전환
                chatgpt_input = []
                instructions = ""
                for msg in final_payload.get("messages", []):
                    if msg["role"] == "system":
                        instructions = msg["content"]
                    else:
                        part_type = "output_text" if msg["role"] == "assistant" else "input_text"
                        chatgpt_input.append({
                            "type": "message",
                            "role": msg["role"],
                            "content": [
                                {
                                    "type": part_type,
                                    "text": msg["content"]
                                }
                            ]
                        })
                final_payload["input"] = chatgpt_input
                if instructions:
                    final_payload["instructions"] = instructions

            # 사전 회수된 장기 기억 지식이 있는 경우 instructions 최상단에 투명 주입
            if recalled_context:
                curr_inst = final_payload.get("instructions", "")
                if recalled_context not in curr_inst:
                    final_payload["instructions"] = f"{recalled_context}\n\n{curr_inst}".strip()

            # /responses 규격의 instructions 영역에도 표준 보고서 가이드라인 투명 주입
            final_payload = SystemDirective.inject_into_payload(final_payload)

        # /responses API로 향하는 요청의 규격 정화 (변환 여부와 상관없이 항상 적용)
        if not MOCK_MODE or "responses" in incoming_path:
            # 불필요한 파라미터 삭제 및 필수 stream 주입 (stream_options는 /responses API에서 400 에러를 유발하므로 제거)
            for k in ["messages", "temperature", "max_tokens", "stream_options"]:
                if k in final_payload:
                    del final_payload[k]
            final_payload["stream"] = True

    # 9. 동적 타겟 업스트림 경로 수립
    if MOCK_MODE:
        mock_suffix = "/v1/responses" if "responses" in incoming_path else "/v1/chat/completions"
        upstream_url = f"http://localhost:18080/mock/enterprise{mock_suffix}"
    else:
        from urllib.parse import urlparse
        parsed_url = urlparse(ENTERPRISE_API_URL)
        base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        # 실서버 연동 시에는 Cloudflare WAF 403 방지를 위해 무조건 /responses로 릴레이
        upstream_url = f"{base_domain}/backend-api/codex/responses"

    # 10. 스트리밍 비동기 포워딩 및 실시간 트랜스파일링 파이프라인
    # 지식 저장소의 문제(Problem)는 항상 사용자의 실제 원본 질문(user_prompt)을 보존
    stored_prompt_text = user_prompt if user_prompt else (substep_prompt or raw_prompt_text)

    # 10-A. Agy (Gemini) 직접 실행 파이프라인
    if target_vendor == "agy":
        agy_adapter = AdapterFactory.get_adapter("agy")
        agy_payload = agy_adapter.from_unified_request(unified_req)
        agy_prompt = agy_payload.get("prompt") or stored_prompt_text

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid_tag = f" [sid: {session_id}]" if session_id else ""
        print(f"[{now_str}]{sid_tag} ➔ [UPSTREAM: AGY GEMINI] Model: {target_model} | Provider: {UPSTREAM_PROVIDER.upper()}", flush=True)

        if unified_req.stream:
            accumulated_bytes = b""
            def append_agy_raw(chunk_bytes: bytes):
                nonlocal accumulated_bytes
                accumulated_bytes += chunk_bytes

            is_responses_api = "responses" in incoming_path
            if is_responses_api:
                gen = agy_adapter.generate_responses_sse_stream(agy_prompt, model=target_model, on_chunk=append_agy_raw)
            else:
                gen = agy_adapter.generate_chat_completions_sse_stream(agy_prompt, model=target_model, on_chunk=append_agy_raw)

            async def agy_stream_generator():
                try:
                    async for sse_chunk in gen:
                        yield sse_chunk
                except (asyncio.CancelledError, GeneratorExit):
                    return
                except Exception as e:
                    print(f"[Error] Agy Stream exception: {e}")
                    err_msg = json.dumps({"error": {"message": f"Agy stream exception: {str(e)}", "type": "agy_error"}})
                    yield f"data: {err_msg}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return
                finally:
                    resp_text = accumulated_bytes.decode("utf-8", errors="ignore")
                    in_tok = max(100, int(len(agy_prompt) * 0.35))
                    out_tok = max(50, int(len(resp_text) * 0.35))
                    loc = global_tracker.extract_code_lines(resp_text)
                    global_tracker.track_request(
                        target_model,
                        decision,
                        in_tok,
                        out_tok,
                        loc=loc,
                        session_id=session_id,
                        auth_token=enterprise_token,
                        account_id=get_latest_enterprise_account_id(),
                        prompt_text=stored_prompt_text,
                        response_text=resp_text
                    )

            return StreamingResponse(agy_stream_generator(), media_type="text/event-stream")
        else:
            res = await agy_adapter.send_request(agy_payload, {}, "")
            resp_data = res.json()
            resp_text = resp_data.get("output_text", "")
            in_tok = max(100, int(len(agy_prompt) * 0.35))
            out_tok = max(50, int(len(resp_text) * 0.35))
            loc = global_tracker.extract_code_lines(resp_text)
            global_tracker.track_request(
                target_model,
                decision,
                in_tok,
                out_tok,
                loc=loc,
                session_id=session_id,
                auth_token=enterprise_token,
                account_id=get_latest_enterprise_account_id(),
                prompt_text=stored_prompt_text,
                response_text=resp_text
            )
            return res

    if unified_req.stream:
        is_passthrough = "responses" in incoming_path
        client = httpx.AsyncClient(timeout=180.0)
        try:
            req = client.build_request("POST", upstream_url, json=final_payload, headers=target_headers, timeout=180.0)
            upstream_res = await client.send(req, stream=True)
        except Exception as e:
            await client.aclose()
            print(f"[Error] Upstream connection failure: {e}")
            return PlainTextResponse(f"Proxy upstream connection failed: {e}", status_code=502)

        # 업스트림이 429, 401, 5xx 등 오류 응답을 반환한 경우:
        # StreamingResponse(HTTP 200)로 감싸지 않고 업스트림 상태 코드 및 본문 그대로 반환하여
        # 클라이언트(Codex/Antigravity)의 SSE 파서 조기 종료 에러를 원천 방지함
        if upstream_res.status_code != 200:
            error_body = await upstream_res.aread()
            await upstream_res.aclose()
            await client.aclose()
            err_text = error_body.decode('utf-8', errors='ignore')
            print(f"[Warning] Upstream API Error Status: {upstream_res.status_code}, Body: {err_text}")

            # Auto-Failover to Agy Gemini if upstream credits depleted (429) or server unavailable (503)
            is_credits_depleted = (
                upstream_res.status_code in (429, 503)
                or "usage_limit_reached" in err_text
                or "credits_depleted" in err_text
                or "workspace_member_credits_depleted" in err_text
            )
            if UPSTREAM_PROVIDER in ("auto", "auto_fallback") and is_credits_depleted:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sid_tag = f" [sid: {session_id}]" if session_id else ""
                fallback_model = os.getenv("AGY_MODEL", "gemini-3.8-flash-high")
                print(f"[{now_str}]{sid_tag} ➔ [FAILOVER: AGY GEMINI] Upstream {upstream_res.status_code} credits depleted! Transparently failing over to agy ({fallback_model})...", flush=True)

                agy_adapter = AdapterFactory.get_adapter("agy")
                agy_payload = agy_adapter.from_unified_request(unified_req)
                agy_prompt = agy_payload.get("prompt") or stored_prompt_text

                accumulated_bytes = b""
                def append_failover_raw(chunk_bytes: bytes):
                    nonlocal accumulated_bytes
                    accumulated_bytes += chunk_bytes

                if is_passthrough:
                    gen = agy_adapter.generate_responses_sse_stream(agy_prompt, model=fallback_model, on_chunk=append_failover_raw)
                else:
                    gen = agy_adapter.generate_chat_completions_sse_stream(agy_prompt, model=fallback_model, on_chunk=append_failover_raw)

                async def failover_stream_generator():
                    try:
                        async for sse_chunk in gen:
                            yield sse_chunk
                    except (asyncio.CancelledError, GeneratorExit):
                        return
                    except Exception as e:
                        print(f"[Error] Failover Agy Stream exception: {e}")
                        err_msg = json.dumps({"error": {"message": f"Failover agy exception: {str(e)}", "type": "failover_error"}})
                        yield f"data: {err_msg}\n\n".encode("utf-8")
                        yield b"data: [DONE]\n\n"
                        return
                    finally:
                        resp_text = accumulated_bytes.decode("utf-8", errors="ignore")
                        in_tok = max(100, int(len(agy_prompt) * 0.35))
                        out_tok = max(50, int(len(resp_text) * 0.35))
                        loc = global_tracker.extract_code_lines(resp_text)
                        global_tracker.track_request(
                            fallback_model,
                            "GEMINI_FAILOVER",
                            in_tok,
                            out_tok,
                            loc=loc,
                            session_id=session_id,
                            auth_token=enterprise_token,
                            account_id=get_latest_enterprise_account_id(),
                            prompt_text=stored_prompt_text,
                            response_text=resp_text
                        )

                return StreamingResponse(failover_stream_generator(), media_type="text/event-stream")

            media_type = upstream_res.headers.get("content-type", "application/json")
            return Response(content=error_body, status_code=upstream_res.status_code, media_type=media_type)

        async def stream_generator():
            accumulated_buffer = b""
            has_tracked = False
            
            def append_raw(chunk_bytes: bytes):
                nonlocal accumulated_buffer
                accumulated_buffer += chunk_bytes

            def trigger_tracking():
                nonlocal has_tracked
                if not has_tracked and accumulated_buffer:
                    has_tracked = True
                    try:
                        global_tracker.parse_and_track_from_buffer(
                            accumulated_buffer,
                            target_model,
                            decision,
                            prompt_text=stored_prompt_text,
                            session_id=session_id,
                            auth_token=enterprise_token,
                            account_id=get_latest_enterprise_account_id()
                        )
                    except Exception as e:
                        print(f"[Warning] Tracking trigger error: {e}")

            try:
                if is_passthrough:
                    # master 브랜치처럼 백엔드가 주는 바이너리 청크 그대로 통과시킴
                    async for chunk in upstream_res.aiter_bytes():
                        accumulated_buffer += chunk
                        yield chunk
                else:
                    # 실시간 트랜스파일링을 물려서 데이터 방출 (원본 수집 콜백 전달)
                    raw_generator = upstream_res.aiter_bytes()
                    async for transpiled_chunk in StreamTranspiler.transpile_stream(raw_generator, source_adapter, target_adapter, on_raw_chunk=append_raw):
                        yield transpiled_chunk
            except (asyncio.CancelledError, GeneratorExit):
                # 클라이언트 연결 종료/취소 정상 반환
                return
            except Exception as e:
                print(f"[Error] Stream routing exception: {e}")
                err_msg = json.dumps({"error": {"message": f"Proxy routing exception: {str(e)}", "type": "proxy_error"}})
                yield f"data: {err_msg}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
                return
            finally:
                await upstream_res.aclose()
                await client.aclose()
                # 클라이언트 즉시 연결 해제(CancelledError) 상황에서도 100% 누락 없는 사용량/기억 수집 (Zero-Drop Guarantee)
                trigger_tracking()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    
    # 11. 논스트림(Non-streaming) 동기 포워딩 파이프라인
    else:
        try:
            res = await target_adapter.send_request(final_payload, target_headers, upstream_url)
            if res.status_code == 200:
                # 사용량 추적기 로깅
                res_data = res.json()
                usage = res_data.get("usage", {}) if isinstance(res_data, dict) else {}
                in_tok = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                out_tok = usage.get("completion_tokens", usage.get("output_tokens", 0))
                if not in_tok and not out_tok:
                    in_tok = max(100, int(len(stored_prompt_text) * 0.35))
                    out_tok = 150
                
                resp_text = ""
                if isinstance(res_data, dict):
                    if "choices" in res_data and res_data["choices"]:
                        msg = res_data["choices"][0].get("message", {})
                        resp_text = msg.get("content", "")
                    elif "output_text" in res_data:
                        resp_text = str(res_data["output_text"])

                loc = global_tracker.extract_code_lines(resp_text)
                global_tracker.track_request(target_model, decision, in_tok, out_tok, loc=loc, session_id=session_id, auth_token=enterprise_token, account_id=get_latest_enterprise_account_id(), prompt_text=stored_prompt_text, response_text=resp_text)
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
        sys_content = msg.get("content", "") if msg.get("role") == "system" else ""
        if "4-Tier LLM 라우터" in sys_content or "비용 절감용 라우터" in sys_content or "라우터" in sys_content:
            is_classification = True
            break
            
    if is_classification:
        verdict = "SILVER"
        if "오타" in last_prompt or "명령어 오타" in last_prompt:
            verdict = "BRONZE"
        elif "리팩토링" in last_prompt or "단순" in last_prompt:
            verdict = "SILVER"
        elif "호출 흐름" in last_prompt or "중간 난이도" in last_prompt:
            verdict = "GOLD"
        elif "복잡한 알고리즘" in last_prompt or "다중 컴포넌트" in last_prompt:
            verdict = "PLATINUM"
        elif "최적화" in last_prompt or "메모리 누수" in last_prompt or "분산 락" in last_prompt or "데드락" in last_prompt:
            verdict = "CHALLENGER"
            
        print(f"[Mock Classifier] Gaming RPG Rank verdict for prompt -> {verdict}")
        
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
