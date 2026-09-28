import unittest
from unittest.mock import patch, MagicMock, AsyncMock
from tierbridge.models import UnifiedRequest, Message
from tierbridge.router import Router


class TestClassifierReserveFallback(unittest.TestCase):
    def setUp(self):
        Router.last_classifier_status = {
            "primary": "gpt-reserve",
            "fallback": "gpt-5.6-luna",
            "last_used": "gpt-reserve",
            "last_timestamp": None
        }

    def _create_mock_response(self, status_code=200, lines=None):
        if lines is None:
            lines = [
                'data: {"choices": [{"delta": {"content": "BRONZE"}, "finish_reason": "stop"}]}',
                'data: [DONE]'
            ]
        mock_resp = MagicMock()
        mock_resp.status_code = status_code

        async def aiter_lines():
            for line in lines:
                yield line

        mock_resp.aiter_lines = aiter_lines
        return mock_resp

    @patch.object(Router, "get_client")
    def test_primary_gpt_reserve_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_resp = self._create_mock_response(200)

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream.return_value = mock_stream_ctx
        mock_get_client.return_value = mock_client

        req = UnifiedRequest(
            model="gpt-5.6-luna",
            messages=[Message(role="user", content="비즈니스 로직 단위 구현 및 회원가입 인증 모듈 개발")]
        )

        import asyncio
        decision, model, effort = asyncio.run(
            Router.classify_request(
                unified_request=req,
                auth_token="Bearer mock-token",
                enterprise_api_url="http://mock-api/responses"
            )
        )

        self.assertEqual(decision, "BRONZE")
        self.assertEqual(Router.last_classifier_status["last_used"], "gpt-reserve")
        # Ensure gpt-reserve was called in stream payload
        call_args = mock_client.stream.call_args
        self.assertEqual(call_args[1]["json"]["model"], "gpt-reserve")

    @patch.object(Router, "get_client")
    def test_fallback_to_luna_on_reserve_failure(self, mock_get_client):
        mock_client = MagicMock()
        fail_resp = MagicMock()
        fail_resp.status_code = 429

        success_resp = self._create_mock_response(200, [
            'data: {"choices": [{"delta": {"content": "SILVER"}, "finish_reason": "stop"}]}',
            'data: [DONE]'
        ])

        stream_calls = [
            MagicMock(__aenter__=AsyncMock(return_value=fail_resp), __aexit__=AsyncMock(return_value=None)),
            MagicMock(__aenter__=AsyncMock(return_value=success_resp), __aexit__=AsyncMock(return_value=None))
        ]
        mock_client.stream.side_effect = stream_calls
        mock_get_client.return_value = mock_client

        req = UnifiedRequest(
            model="gpt-5.6-luna",
            messages=[Message(role="user", content="비즈니스 로직 리팩토링")]
        )

        import asyncio
        decision, model, effort = asyncio.run(
            Router.classify_request(
                unified_request=req,
                auth_token="Bearer mock-token",
                enterprise_api_url="http://mock-api/responses"
            )
        )

        self.assertEqual(decision, "SILVER")
        self.assertEqual(Router.last_classifier_status["last_used"], "gpt-5.6-luna-fallback")
        self.assertEqual(mock_client.stream.call_count, 2)


if __name__ == "__main__":
    unittest.main()
