import os

class AuthManager:
    @staticmethod
    def resolve_auth_headers(request_headers: dict, source_vendor: str, target_vendor: str) -> dict:
        """
        인바운드 요청 헤더를 검사하고, 타겟 백엔드 벤더의 규격에 맞는 적합한 인증 헤더로 변환/조정합니다.
        동일 벤더 라우팅의 경우 기존 인증 토큰을 패스스루하고,
        이종 벤더 크로스 라우팅의 경우 로컬 환경 변수에서 찾아 키를 스왑합니다.
        """
        resolved_headers = {}
        
        # 1. 원본 요청 헤더에서 대소문자 무관하게 인증 헤더 추출
        auth_header_keys = ["authorization", "x-api-key", "api-key", "x-goog-api-key"]
        extracted_headers = {}
        for k, v in request_headers.items():
            k_lower = k.lower()
            if k_lower in auth_header_keys:
                extracted_headers[k_lower] = v

        # 2. 동일 벤더 라우팅의 경우 -> 기존 인증 정보 패스스루 (Authentication Delegation)
        if source_vendor == target_vendor:
            for key, val in extracted_headers.items():
                resolved_headers[key] = val
                
        # 3. 이종 벤더 교차 라우팅의 경우 -> 환경 변수를 조회하여 적합한 헤더로 스왑
        else:
            if target_vendor == "openai":
                api_key = os.getenv("OPENAI_API_KEY")
                if api_key:
                    resolved_headers["authorization"] = f"Bearer {api_key}"
                elif "authorization" in extracted_headers:
                    resolved_headers["authorization"] = extracted_headers["authorization"]
                    
            elif target_vendor == "anthropic":
                api_key = os.getenv("ANTHROPIC_API_KEY")
                if api_key:
                    resolved_headers["x-api-key"] = api_key
                elif "x-api-key" in extracted_headers:
                    resolved_headers["x-api-key"] = extracted_headers["x-api-key"]
                elif "api-key" in extracted_headers:
                    resolved_headers["x-api-key"] = extracted_headers["api-key"]
                    
            elif target_vendor == "gemini":
                api_key = os.getenv("GEMINI_API_KEY")
                if api_key:
                    resolved_headers["x-goog-api-key"] = api_key
                elif "x-goog-api-key" in extracted_headers:
                    resolved_headers["x-goog-api-key"] = extracted_headers["x-goog-api-key"]

        # Content-Type이나 기본 헤더는 호출부에서 다시 보강하므로, 여기서는 인증 필터링만 완료하여 리턴합니다.
        return resolved_headers
