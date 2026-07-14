import json
from typing import AsyncGenerator
from tierbridge.adapters.base import BaseAdapter

class StreamTranspiler:
    @staticmethod
    async def transpile_stream(
        upstream_generator: AsyncGenerator[bytes, None],
        source_adapter: BaseAdapter,
        target_adapter: BaseAdapter,
        on_raw_chunk = None
    ) -> AsyncGenerator[bytes, None]:
        """
        비동기 바이트 스트림을 한 줄씩 읽어, 타겟 벤더의 포맷에서 소스 벤더(클라이언트) 포맷으로
        실시간 번역하여 yield하는 제너레이터입니다.
        on_raw_chunk 콜백을 제공하면 수신된 원본 바이너리를 실시간 모니터링/버퍼링할 수 있습니다.
        """
        buffer = ""
        
        async for chunk in upstream_generator:
            if on_raw_chunk:
                on_raw_chunk(chunk)
                
            decoded_chunk = chunk.decode("utf-8", errors="ignore")
            buffer += decoded_chunk
            
            # SSE 스트림은 더블 줄바꿈(\n\n)으로 청크를 분할함
            while "\n\n" in buffer:
                single_chunk, buffer = buffer.split("\n\n", 1)
                single_chunk = single_chunk.strip()
                if not single_chunk:
                    continue
                
                # 1. 타겟 어댑터의 규격으로 스트림 청크 파싱 -> 순수 텍스트와 종료 여부 추출
                text, is_done = target_adapter.parse_stream_chunk(single_chunk)
                
                # 2. 소스 에이전트 규격에 맞춰 새로운 SSE 데이터로 패키징
                if text or is_done:
                    formatted_sse = source_adapter.format_stream_chunk(text, is_done)
                    yield formatted_sse.encode("utf-8")
        
        # 마지막 잔여 버퍼 처리
        if buffer.strip():
            text, is_done = target_adapter.parse_stream_chunk(buffer.strip())
            if text or is_done:
                formatted_sse = source_adapter.format_stream_chunk(text, is_done)
                yield formatted_sse.encode("utf-8")
