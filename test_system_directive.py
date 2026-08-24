import unittest
from tierbridge.models import UnifiedRequest, Message
from tierbridge.system_directive import SystemDirective


class TestSystemDirective(unittest.TestCase):
    def test_inject_into_unified_request_without_system(self):
        req = UnifiedRequest(
            model="gpt-5.6-luna",
            messages=[Message(role="user", content="테스트 질문")]
        )
        updated = SystemDirective.inject_into_unified_request(req)
        self.assertEqual(len(updated.messages), 2)
        self.assertEqual(updated.messages[0].role, "system")
        self.assertIn("최종 답변 작성 시 표준 보고서 포맷 준수", updated.messages[0].content)

    def test_inject_into_unified_request_with_existing_system(self):
        req = UnifiedRequest(
            model="gpt-5.6-luna",
            messages=[
                Message(role="system", content="You are a helpful assistant."),
                Message(role="user", content="테스트 질문")
            ]
        )
        updated = SystemDirective.inject_into_unified_request(req)
        self.assertEqual(len(updated.messages), 2)
        self.assertEqual(updated.messages[0].role, "system")
        self.assertIn("You are a helpful assistant.", updated.messages[0].content)
        self.assertIn("최종 답변 작성 시 표준 보고서 포맷 준수", updated.messages[0].content)

    def test_inject_into_payload_responses_format(self):
        payload = {
            "instructions": "Original system instructions."
        }
        updated = SystemDirective.inject_into_payload(payload)
        self.assertIn("Original system instructions.", updated["instructions"])
        self.assertIn("최종 답변 작성 시 표준 보고서 포맷 준수", updated["instructions"])


if __name__ == "__main__":
    unittest.main()
