import sys
import os
import unittest
import asyncio
import httpx
from unittest.mock import patch, MagicMock, AsyncMock

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from fastapi.testclient import TestClient
from harness import app

class TestStreamResilience(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("harness.httpx.AsyncClient")
    async def test_upstream_429_clean_streaming_without_asgi_crash(self, mock_client_cls):
        # Mock upstream 429 response in chatgpt-only mode
        with patch("harness.UPSTREAM_PROVIDER", "chatgpt"):
            mock_res = AsyncMock()
            mock_res.status_code = 429
            mock_res.headers = {"content-type": "application/json"}
            mock_res.aread = AsyncMock(return_value=b'{"error":{"type":"usage_limit_reached","message":"The usage limit has been reached"}}')
            mock_res.aclose = AsyncMock()
            
            mock_client = AsyncMock()
            mock_client.build_request = MagicMock(return_value=MagicMock())
            mock_client.send = AsyncMock(return_value=mock_res)
            mock_client.aclose = AsyncMock()
            mock_client_cls.return_value = mock_client

            # Send streaming request to proxy
            payload = {
                "model": "gpt-6-luna",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True
            }
            
            # Should return 429 directly without stream parse crash
            res = self.client.post("/v1/chat/completions", json=payload)
            self.assertEqual(res.status_code, 429)
            content = res.text
            self.assertIn("usage_limit_reached", content)
            mock_res.aclose.assert_awaited()
            mock_client.aclose.assert_awaited()

    @patch("harness.httpx.AsyncClient")
    async def test_upstream_429_auto_failover_to_agy(self, mock_client_cls):
        # Mock upstream 429 response in auto mode -> transparent failover to agy
        with patch("harness.UPSTREAM_PROVIDER", "auto"):
            mock_res = AsyncMock()
            mock_res.status_code = 429
            mock_res.headers = {"content-type": "application/json"}
            mock_res.aread = AsyncMock(return_value=b'{"error":{"type":"usage_limit_reached","message":"The usage limit has been reached"}}')
            mock_res.aclose = AsyncMock()
            
            mock_client = AsyncMock()
            mock_client.build_request = MagicMock(return_value=MagicMock())
            mock_client.send = AsyncMock(return_value=mock_res)
            mock_client.aclose = AsyncMock()
            mock_client_cls.return_value = mock_client

            payload = {
                "model": "gpt-6-luna",
                "messages": [{"role": "user", "content": "ping"}],
                "stream": True
            }

            # In auto mode, upstream 429 triggers failover to agy returning 200 SSE stream
            with patch("tierbridge.adapters.agy_adapter.AgyAdapter.stream_agy_process") as mock_stream:
                async def fake_chunks(prompt, model):
                    yield "Hello from "
                    yield "Gemini"
                mock_stream.side_effect = fake_chunks
                res = self.client.post("/v1/chat/completions", json=payload)
                self.assertEqual(res.status_code, 200)
                self.assertIn("Hello from ", res.text)
                self.assertIn("Gemini", res.text)

    @patch("harness.httpx.AsyncClient")
    async def test_stream_connection_error_returns_502(self, mock_client_cls):
        # Mock upstream connection error
        mock_client = AsyncMock()
        mock_client.build_request = MagicMock(return_value=MagicMock())
        mock_client.send.side_effect = httpx.ConnectError("Connection refused by mock")
        mock_client.aclose = AsyncMock()
        mock_client_cls.return_value = mock_client

        payload = {
            "model": "gpt-6-luna",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": True
        }
        res = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(res.status_code, 502)
        self.assertIn("Proxy upstream connection failed", res.text)
        mock_client.aclose.assert_awaited()

if __name__ == "__main__":
    unittest.main()
