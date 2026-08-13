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
        code_blocks = re.findall(r'```[\w\-]*\n(.*?)```', full_text, re.DOTALL)
        for block in code_blocks:
            lines = [line for line in block.splitlines() if line.strip()]
            loc_count += len(lines)
        return loc_count

    def track_request(self, model: str, decision: str, input_tokens: int, output_tokens: int, loc: int = 0, session_id: str = ""):
        """
        토큰 소모량 및 코드 작성 줄 수(LOC)를 전달받아 예상 비용을 계산하고 통계 세션에 누적합니다.
        """
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
        
        sid_tag = f" [sid: {session_id}]" if session_id else ""
        print(f"[{timestamp_str}]{sid_tag} ➔ [USAGE] {decision} ({model}) | input={input_tokens} output={output_tokens} tokens | loc={loc} lines | cost=${round(cost_total, 6)} USD", flush=True)

    def parse_and_track_from_buffer(self, buffer: bytes, model: str, decision: str, prompt_text: str = "", session_id: str = ""):
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
                        
                    # 2. 응답 텍스트 조각 수집 (LOC 파싱 및 출력 토큰 추정용)
                    if event.get("type") == "response.content_part.delta":
                        delta_part = event.get("delta", {})
                        if isinstance(delta_part, dict) and delta_part.get("type") == "text":
                            response_full_text += delta_part.get("text", "")
                    elif event.get("type") == "response.output_text.delta":
                        delta_text = event.get("delta")
                        if isinstance(delta_text, str):
                            response_full_text += delta_text
                    elif event.get("choices"):
                        c = event["choices"][0]
                        delta_c = c.get("delta", {})
                        if delta_c.get("content"):
                            response_full_text += delta_c["content"]
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

            self.track_request(model, decision, input_tokens, output_tokens, loc, session_id=session_id)
        except Exception as e:
            print(f"[Warning] Failed to parse usage stats from buffer: {e}")
