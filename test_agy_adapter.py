import os
import sys
import unittest
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from tierbridge.adapters.agy_adapter import AgyAdapter
from tierbridge.models import UnifiedRequest, Message
from harness import app

class TestAgyAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = AgyAdapter(default_model="gemini-3.8-flash-high")
        self.client = TestClient(app)

    def test_to_unified_request_openai_format(self):
        raw = {
            "model": "gemini-3.8-flash-high",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello world"}
            ]
        }
        req = self.adapter.to_unified_request(raw)
        self.assertEqual(req.system_instruction, "You are a helpful assistant.")
        self.assertEqual(len(req.messages), 1)
        self.assertEqual(req.messages[0].content, "Hello world")
        self.assertEqual(req.model, "gemini-3.8-flash-high")

    def test_to_unified_request_responses_format(self):
        raw = {
            "model": "agy",
            "instructions": "System guidelines",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "Task A"}]},
                {"role": "assistant", "content": [{"type": "output_text", "text": "Done A"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "Task B"}]}
            ]
        }
        req = self.adapter.to_unified_request(raw)
        self.assertEqual(req.system_instruction, "System guidelines")
        self.assertEqual(len(req.messages), 3)
        self.assertEqual(req.messages[0].content, "Task A")
        self.assertEqual(req.messages[1].role, "assistant")
        self.assertEqual(req.messages[2].content, "Task B")

    def test_from_unified_request_prompt_formatting(self):
        req = UnifiedRequest(
            system_instruction="Guideline 1",
            messages=[
                Message(role="user", content="Question 1"),
                Message(role="assistant", content="Answer 1"),
                Message(role="user", content="Question 2")
            ],
            model="gemini-3.8-flash-high"
        )
        payload = self.adapter.from_unified_request(req)
        self.assertIn("[System Instruction]\nGuideline 1", payload["prompt"])
        self.assertIn("[User]:\nQuestion 1", payload["prompt"])
        self.assertIn("[Assistant]:\nAnswer 1", payload["prompt"])
        self.assertIn("[User]:\nQuestion 2", payload["prompt"])
        self.assertEqual(payload["model"], "gemini-3.8-flash-high")

    def test_direct_agy_routing_chat_completions(self):
        with patch.object(AgyAdapter, "stream_agy_process") as mock_stream:
            async def fake_stream(prompt, model):
                yield "Gemini "
                yield "3.8 "
                yield "response"
            mock_stream.side_effect = fake_stream

            res = self.client.post("/v1/chat/completions", json={
                "model": "gemini-3.8-flash-high",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn("Gemini ", res.text)
            self.assertIn("3.8 ", res.text)
            self.assertIn("response", res.text)
            self.assertIn("data: [DONE]", res.text)

    def test_direct_agy_routing_responses(self):
        with patch.object(AgyAdapter, "stream_agy_process") as mock_stream:
            async def fake_stream(prompt, model):
                yield "Codex "
                yield "relay"
            mock_stream.side_effect = fake_stream

            res = self.client.post("/v1/responses", json={
                "model": "agy",
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
                "stream": True
            })
            self.assertEqual(res.status_code, 200)
            self.assertIn("response.output_text.delta", res.text)
            self.assertIn("response.completed", res.text)
            self.assertIn("data: [DONE]", res.text)

if __name__ == "__main__":
    unittest.main()
