# 📑 하네스 투명 최종 보고서 표준 규격 가이드 (Standard Report Directive)

이 문서는 TierBridge 하네스 프록시가 클라이언트(Codex CLI / Agent CLI)와 업스트림 AI 모델 간 통신을 중계할 때, 사용자에게 노출되지 않는 백그라운드 시스템 지시문(Developer Instruction) 영역에 **[최종 보고서 표준 규격 가이드]**를 투명하게 주입하여, 최종 답변이 일관된 **3단 보고서 포맷(요구사항 요약 / 변경 파일 및 코드 / 검증 결과)**으로 생성·적재되도록 하는 표준 규격 문서입니다.

---

## 1. 개요 및 목적 (Objectives)

1. **지식 재활용 효율 극대화 (Knowledge Usability)**:
   - LLM이 자유 서술형으로 장황하게 답변하지 않고, `요구사항 의도`, `수정 파일/코드`, `검증 결과`의 명확한 3단 구조로 출력하게 함으로써 나중에 장기 기억저장소(`memory.db`)에서 검색·회수되었을 때 다음 LLM이 즉시 핵심 결론을 파악할 수 있도록 함.
2. **사용자 가독성 향상 (Developer Experience)**:
   - 터미널 출력 결과가 체계적인 보고서 형식으로 정돈되어, 작업 완료 후 diff와 검증 상태를 직관적으로 파악 가능.
3. **완전 투명한 백그라운드 주입 (Zero-Impact on User)**:
   - 사용자가 입력한 원본 프롬프트에는 일체 손을 대지 않고, 업스트림 모델로 전달되는 시스템 지시문(`instructions` / `system messages`)에만 자동 병합.

---

## 2. 표준 보고서 지시문 규격 (Directive Specification)

```markdown
[지침: 최종 답변 작성 시 표준 보고서 포맷 준수]
모든 도구 실행 및 분석이 끝나고 사용자에게 최종 완료 보고를 작성할 때는, 반드시 아래 3단 마크다운 포맷에 맞추어 명확하게 구조화하여 작성하세요:

### 🎯 1. 요구사항 및 문제 핵심 요약
- 사용자의 최초 의도 및 해결 목표

### 🛠️ 2. 변경 및 구현 사항
- **수정/참조 파일**: \`경로/파일명\`
- **핵심 로직/코드**: (변경된 주요 코드 스니펫 및 설명)

### ✅ 3. 검증 및 테스트 결과
- 테스트 실행 결과 및 빌드/호환성 검증 내용
```

---

## 3. 주입 메커니즘 (Injection Pipeline)

1. **OpenAI / ChatGPT Enterprise (`/backend-api/codex/responses`)**:
   - `instructions` 필드가 존재하면 해당 문자열 뒤에 가이드라인 추가.
   - `instructions`가 없으면 신규 가이드라인 생성 대입.
2. **OpenAI Chat Completions (`/v1/chat/completions`) & Anthropic / Gemini**:
   - `messages`의 `role == "system"` 메시지에 추가하거나, 첫 번째 메시지 앞에 `role: "system"`으로 삽입.
