import json

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
        self.total_cost_usd = 0.0
        self.history = []

    def get_summary(self) -> dict:
        return {
            "session_summary": {
                "total_requests": self.total_requests,
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_tokens": self.total_input_tokens + self.total_output_tokens,
                "total_cost_usd": round(self.total_cost_usd, 6)
            },
            "per_request_history": self.history
        }

    def track_request(self, model: str, decision: str, input_tokens: int, output_tokens: int):
        """
        토큰 소모량을 전달받아 예상 비용을 계산하고 통계 세션에 누적합니다.
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
        
        self.total_requests += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost_total
        
        self.history.append({
            "model": model,
            "decision": decision,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_total, 6)
        })
        
        print(f"➔ [USAGE] {decision} ({model}) | input={input_tokens} output={output_tokens} tokens | cost=${round(cost_total, 6)} USD")

    def parse_and_track_from_buffer(self, buffer: bytes, model: str, decision: str):
        """
        스트리밍 버퍼에 쌓인 SSE 최종 응답 텍스트를 파싱하여 토큰 소모량을 식별 및 수집합니다.
        """
        try:
            text = buffer.decode("utf-8", errors="ignore")
            input_tokens = 0
            output_tokens = 0
            
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                    
                    # 1. response.completed 또는 response 구조 탐색 (ChatGPT Enterprise)
                    if "response" in event and isinstance(event["response"], dict):
                        usage = event["response"].get("usage", {})
                        if usage:
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            
                    # 2. 일반 OpenAI chat completions 규격의 usage 필드 탐색
                    elif "usage" in event and event["usage"]:
                        usage = event["usage"]
                        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
                        output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
                        
                except Exception:
                    continue
            
            if input_tokens or output_tokens:
                self.track_request(model, decision, input_tokens, output_tokens)
        except Exception as e:
            print(f"[Warning] Failed to parse usage stats from buffer: {e}")
