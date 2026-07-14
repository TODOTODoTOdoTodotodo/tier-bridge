from abc import ABC, abstractmethod
from typing import AsyncGenerator, Tuple
from tierbridge.models import UnifiedRequest
import httpx

class BaseAdapter(ABC):
    @abstractmethod
    def to_unified_request(self, raw_request_body: dict) -> UnifiedRequest:
        """인바운드 에이전트의 원본 요청을 내부 정규화 모델로 변환"""
        pass

    @abstractmethod
    def from_unified_request(self, unified_request: UnifiedRequest) -> dict:
        """내부 정규화 모델을 아웃바운드 대상 백엔드 규격 요청 바디로 변환"""
        pass

    @abstractmethod
    async def send_request(self, payload: dict, headers: dict, target_url: str) -> httpx.Response:
        """실제 백엔드 API로 비동기 HTTP 요청을 전송"""
        pass

    @abstractmethod
    def parse_stream_chunk(self, chunk_text: str) -> Tuple[str, bool]:
        """
        백엔드로부터 수신한 스트림 청크 문자열을 파싱하여 (추가될_텍스트, 스트림_종료_여부) 반환
        """
        pass

    @abstractmethod
    def format_stream_chunk(self, text: str, is_done: bool) -> str:
        """
        클라이언트 에이전트 포맷에 맞춘 SSE 데이터 형식의 청크 스트링 반환
        """
        pass
