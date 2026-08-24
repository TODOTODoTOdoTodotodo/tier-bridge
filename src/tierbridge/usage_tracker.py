import json
import re
from datetime import datetime

class UsageTracker:
    # 100만 토큰당 가격 (USD)
    PRICE_CATALOG = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-5.6-terra": {"input": 2.50, "output": 10.00},  # 임의 설정 단가
        "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "unknown": {"input": 1.00, "output": 3.00}
    }

    def __init__(self):
        self.total_requests = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_loc = 0
        self.total_cost_usd = 0.0
        self.history = []
        self.seen_sessions = set()

    def get_summary(self) -> dict:
        return {
            "session_summary": {
                "total_requests": self.total_requests,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "total_loc": self.total_loc,
                "total_cost_usd": round(self.total_cost_usd, 6)
            },
            "per_request_history": self.history
        }

    @staticmethod
    def extract_code_lines(full_text: str) -> int:
        """
        마크다운 응답 텍스트에서 코드 블록(``` ... ```) 내부의 소스코드 줄 수(LOC)를 계산합니다.
        """
        if not full_text:
            return 0
        
        loc_count = 0
        # 모든 프로그래밍 언어 태그(ts, vue, java, bash 등) 및 줄바꿈 지원
        code_blocks = re.findall(r"```[^\n]*\r?\n(.*?)```", full_text, re.DOTALL)
        for block in code_blocks:
            lines = [line for line in block.splitlines() if line.strip()]
            loc_count += len(lines)
        return loc_count

    def track_request(self, model: str, decision: str, input_tokens: int, output_tokens: int, loc: int = 0, session_id: str = "", auth_token: str = "", account_id: str = "", is_first_turn: Optional[bool] = None, prompt_text: str = "", response_text: str = ""):
        """
        단일 LLM 호출 턴의 사용량을 기록하고, 실시간 델타 크레딧 인터셉터 및 기억 저장소 워커를 비동기 구동합니다.
        """
        # LOC 2중 안전망: loc가 0이고 response_text가 제공된 경우 자동 계산
        if loc == 0 and response_text:
            loc = self.extract_code_lines(response_text)

        # 모델명 소문자 매핑
        model_key = model.lower()
        matched_catalog = self.PRICE_CATALOG.get("unknown")
        
        for key in self.PRICE_CATALOG:
            if key in model_key:
                matched_catalog = self.PRICE_CATALOG[key]
                break
                
        # 1M 토큰당 가격 기준이므로 100만으로 나눔
        cost_in = (input_tokens * matched_catalog["input"]) / 1_000_000.0
        cost_out = (output_tokens * matched_catalog["output"]) / 1_000_000.0
        cost_total = cost_in + cost_out

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        iso_timestamp = now.isoformat()
        
        self.total_requests += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_loc += loc
        self.total_cost_usd += cost_total
        
        self.history.append({
            "timestamp": iso_timestamp,
            "model": model,
            "decision": decision,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "loc": loc,
            "cost_usd": round(cost_total, 6)
        })

        # 세션 최초 턴 여부 식별
        if is_first_turn is None:
            if session_id:
                is_first = session_id not in self.seen_sessions
                self.seen_sessions.add(session_id)
            else:
                is_first = False
        else:
            is_first = is_first_turn
        
        # 1. 실시간 델타 크레딧 인터셉터 비동기 백그라운드 구동 (0ms 클라이언트 레이턴시)
        try:
            try:
                from tierbridge.credit_interceptor import interceptor
            except ImportError:
                from src.tierbridge.credit_interceptor import interceptor
            
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(interceptor.track_turn_delta(
                session_id=session_id,
                decision=decision,
                model=model,
                in_tok=input_tokens,
                out_tok=output_tokens,
                loc=loc,
                est_cost=round(cost_total, 6),
                auth_token=auth_token,
                account_id=account_id,
                now_str=timestamp_str
            ))
        except Exception:
            # 비동기 루프가 없거나 예외 시 즉시 폴백 로깅
            sid_tag = f" [sid: {session_id}]" if session_id else ""
            print(f"[{timestamp_str}]{sid_tag} ➔ [USAGE] {decision} ({model}) | input={input_tokens} output={output_tokens} tokens | loc={loc} lines | cost=${round(cost_total, 6)} USD", flush=True)

        # 2. Step 1: 비동기 세션 로그 수집 및 기억 저장소(sub-memory) 연동 (0ms 클라이언트 레이턴시)
        try:
            try:
                from tierbridge.memory_ingestion_worker import MemoryIngestionWorker
            except ImportError:
                from src.tierbridge.memory_ingestion_worker import MemoryIngestionWorker
            
            import asyncio
            loop = asyncio.get_running_loop()
            event_data = {
                "session_id": session_id,
                "prompt": prompt_text,
                "decision": decision,
                "loc": loc,
                "cost": round(cost_total, 6),
                "is_first_turn": is_first,
                "solution": response_text
            }
            loop.create_task(MemoryIngestionWorker.process_log_event(event_data))
        except Exception:
            pass

    def parse_and_track_from_buffer(self, buffer: bytes, model: str, decision: str, prompt_text: str = "", session_id: str = "", auth_token: str = "", account_id: str = ""):
        """
        스트리밍 버퍼에 쌓인 SSE 최종 응답 텍스트를 파싱하여 토큰 소모량 및 코드 라인 수(LOC)를 식별 및 수집합니다.
        업스트림 API에서 usage 정보가 유실된 경우에도 prompt_text 기반 추정 폴백으로 Zero-Drop USAGE를 보장하며, session_id를 기록합니다.
        """
        try:
            text = buffer.decode("utf-8", errors="ignore")
            input_tokens = 0
            output_tokens = 0
            response_full_text = ""
            
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                    if not isinstance(event, dict):
                        continue
                    
                    # 1. 다각도 usage 필드 탐색 (ChatGPT Enterprise / OpenAI responses / Chat Completions 규격 지원)
                    candidate_usage = None
                    if "response" in event and isinstance(event["response"], dict):
                        candidate_usage = event["response"].get("usage")
                    if not candidate_usage and "usage" in event:
                        candidate_usage = event["usage"]
                        
                    if candidate_usage and isinstance(candidate_usage, dict):
                        in_val = candidate_usage.get("input_tokens") or candidate_usage.get("prompt_tokens") or 0
                        out_val = candidate_usage.get("output_tokens") or candidate_usage.get("completion_tokens") or 0
                        if in_val:
                            input_tokens = in_val
                        if out_val:
                            output_tokens = out_val
                        
                    # 2. 다각도 응답 텍스트 조각 수집 (OpenAI / Codex responses / Anthropic / Gemini 규격 완벽 지원)
                    t_type = event.get("type", "")
                    
                    if t_type in ("response.text.delta", "response.output_text.delta", "response.output_item.delta"):
                        d = event.get("delta")
                        if isinstance(d, str):
                            response_full_text += d
                        elif isinstance(d, dict):
                            response_full_text += d.get("text", "") or d.get("content", "")
                    elif t_type in ("response.content_part.delta", "content_block_delta"):
                        d = event.get("delta", {})
                        if isinstance(d, dict):
                            response_full_text += d.get("text", "") or d.get("content", "")
                        elif isinstance(d, str):
                            response_full_text += d
                    elif t_type in ("response.done", "response.completed"):
                        # 완료 이벤트에서 전체 텍스트 보강
                        resp_obj = event.get("response", {})
                        if isinstance(resp_obj, dict):
                            if "output_text" in resp_obj and isinstance(resp_obj["output_text"], str) and resp_obj["output_text"]:
                                if not response_full_text:
                                    response_full_text = resp_obj["output_text"]
                            elif "output" in resp_obj and isinstance(resp_obj["output"], list):
                                for out_item in resp_obj["output"]:
                                    if isinstance(out_item, dict) and "content" in out_item:
                                        for c_item in out_item.get("content", []):
                                            if isinstance(c_item, dict) and "text" in c_item:
                                                if not response_full_text:
                                                    response_full_text += c_item.get("text", "")
                    elif event.get("choices"):
                        c = event["choices"][0]
                        delta_c = c.get("delta", {})
                        if isinstance(delta_c, dict) and delta_c.get("content"):
                            response_full_text += delta_c["content"]
                        elif isinstance(c.get("message"), dict) and c["message"].get("content"):
                            if not response_full_text:
                                response_full_text = c["message"]["content"]
                except Exception:
                    continue
            
            loc = self.extract_code_lines(response_full_text)
            
            # Zero-Drop Guarantee: API에서 usage가 포함되지 않은 스트림 응답인 경우 프롬프트/답변 길이 기반 폴백 수집
            if input_tokens == 0 and output_tokens == 0:
                if prompt_text:
                    input_tokens = max(100, int(len(prompt_text) * 0.35))
                else:
                    input_tokens = 500
                    
                if response_full_text:
                    output_tokens = max(20, int(len(response_full_text) * 0.35))
                else:
                    output_tokens = 150

            self.track_request(model, decision, input_tokens, output_tokens, loc, session_id=session_id, auth_token=auth_token, account_id=account_id, prompt_text=prompt_text, response_text=response_full_text)
        except Exception as e:
            print(f"[Warning] Failed to parse usage stats from buffer: {e}")
