"""
SystemDirective: 하네스 레벨 백그라운드 투명 시스템 가이드라인 관리 모듈
"""

from typing import Dict, Any, List, Optional
from tierbridge.models import UnifiedRequest, Message


class SystemDirective:
    """
    개발자 시스템 지시문(Developer Instruction) 주입 핸들러
    """

    STANDARD_REPORT_GUIDE = (
        "[지침: 최종 답변 작성 시 표준 보고서 포맷 준수]\n"
        "모든 도구 실행 및 분석이 끝나고 사용자에게 최종 완료 보고를 작성할 때는, 반드시 아래 3단 마크다운 포맷에 맞추어 명확하게 구조화하여 작성하세요:\n\n"
        "### 🎯 1. 요구사항 및 문제 핵심 요약\n"
        "- 사용자의 최초 의도 및 해결 목표\n\n"
        "### 🛠️ 2. 변경 및 구현 사항\n"
        "- **수정/참조 파일**: `경로/파일명`\n"
        "- **핵심 로직/코드**: (변경된 주요 코드 스니펫 및 설명)\n\n"
        "### ✅ 3. 검증 및 테스트 결과\n"
        "- 테스트 실행 결과 및 빌드/호환성 검증 내용"
    )

    @classmethod
    def inject_into_unified_request(cls, req: UnifiedRequest) -> UnifiedRequest:
        """
        UnifiedRequest의 system 메시지에 표준 보고서 가이드라인 병합
        """
        if not req:
            return req

        has_system = False
        for msg in req.messages:
            if msg.role == "system":
                if cls.STANDARD_REPORT_GUIDE not in msg.content:
                    msg.content = f"{msg.content.strip()}\n\n{cls.STANDARD_REPORT_GUIDE}"
                has_system = True
                break

        if not has_system:
            req.messages.insert(0, Message(role="system", content=cls.STANDARD_REPORT_GUIDE))

        return req

    @classmethod
    def inject_into_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        /responses 규격의 instructions 또는 input 영역에 가이드라인 투명 주입
        """
        if not isinstance(payload, dict):
            return payload

        # 1. instructions 필드가 있는 경우 (ChatGPT Enterprise /responses)
        curr_inst = payload.get("instructions", "")
        if curr_inst:
            if cls.STANDARD_REPORT_GUIDE not in curr_inst:
                payload["instructions"] = f"{curr_inst.strip()}\n\n{cls.STANDARD_REPORT_GUIDE}"
        else:
            payload["instructions"] = cls.STANDARD_REPORT_GUIDE

        return payload
