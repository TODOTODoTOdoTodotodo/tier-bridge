# 🧠 Controller Specification: Memory Prefetch Cache Optimizer & Background Task Bypass

- **Controller File**: `Controller/memory_prefetch_cache_optimizer_controller.md`
- **Related Components**:
  - `src/tierbridge/memory_prefetcher.py` (`MemoryPrefetcher`)
  - `harness.py` (`RecallHook`, `Router`)
  - `src/tierbridge/router.py`
- **Target Policy**: Documentation First Policy & Prompt Caching Cost Optimization

---

## 1. 개요 및 목적 (Context & Purpose)

하네스 프록시의 장기 기억 회수(Memory Prefetch Recall) 기능은 세션 간 단절 시 발생하는 수만 토큰 규모의 맹목적 파일/커밋 탐색 루프(Blind Search, 5~8턴)를 1턴으로 압축하여 큰 폭의 토큰 및 크레딧을 절감하고 있습니다.

그러나 실측 로그 분석 결과 다음 2가지 구조적 비효율이 관측되었습니다:
1. **OpenAI Prompt Caching 접두사(Prefix) 파괴**:
   - `unified_req.messages.insert(0, Message(role="system", content=recalled_context))` 방식으로 인덱스 0번에 가변적인 기억 텍스트를 주입함.
   - 인덱스 0번의 시스템 프롬프트는 15,000~30,000 토큰에 달하는 고정 캐시 대상인데, 인덱스 0번에 기억이 끼어들면서 시스템 프롬프트가 인덱스 1번으로 밀려나 **Exact Prefix Hash Match(정확한 접두사 해시 일치)가 깨지고 80% 캐시 할인이 무효화**될 위험이 발생함.
   - 또한 2턴 이후의 서브스텝에서는 새 유저 턴이 아니므로 인덱스 0번이 다시 원래 시스템 프롬프트로 복귀하여, 1턴과 2턴 간에도 프리픽스가 불일치함.
2. **IDE 내부 백그라운드 태스크의 불필요한 기억 회수 (8.5%)**:
   - `Generate a concise, single-line task title...` (채팅 탭 제목 짓기)
   - `Write a brief catch-up for a user...` (세션 요약 캐치업)
   - `CONTEXT CHECKPOINT COMPACTION...` (컨텍스트 압축)
   - 위와 같은 IDE 자체 관리용 1회성 턴에도 메모리가 회수되어 ~300토큰이 불필요하게 주입됨.

본 컨트롤러는 **(1) 시스템 프롬프트 프리픽스 해시를 100% 보존하는 유저 턴 후미 주입(User Message Suffix Injection)**과 **(2) IDE 내부 백그라운드 태스크 사전 필터링(Bypass Filter)**을 규정합니다.

---

## 2. 도메인 분석 및 아키텍처 원칙 (Domain Analysis & Architectural Invariants)

### 2.1 OpenAI Prompt Caching 메커니즘
OpenAI의 프롬프트 캐싱은 메시지 배열의 첫 번째 토큰(`messages[0]`)부터 시작하는 **Exact Prefix Match** 방식으로 동작합니다.
- **요구조건**: 최소 1,024 토큰 이상의 동일한 접두사.
- **할인율**: 캐시 적중 시 Input 토큰 80% 할인 (정가 대비 1/5 가격).
- **위반 시 결과**: 단 1자라도 첫머리에 추가/변경되면 그 뒤의 수만 토큰 전체가 Uncached(정가)로 청구됨.

### 2.2 핵심 불변식 (Invariants)
1. **[Invariant 1] 시스템 프롬프트 인덱스 0번 불변 원칙**:
   - `messages[0]`에 위치한 IDE 코어 시스템 프롬프트는 절대로 위치가 변경되거나 앞에 다른 메시지가 삽입되어서는 안 됨.
2. **[Invariant 2] RAG 컨텍스트의 유저 프롬프트 국소화**:
   - 회수된 연관 지식(`recalled_context`)은 현재 턴의 사용자 메시지(`messages[-1]`) 하단에 분리자(`---`)와 함께 첨부되어야 함.
   - 이를 통해 `messages[0]`부터 `messages[-2]`까지의 모든 이전 컨텍스트는 비트 단위로 완벽하게 유지되어 90% 이상의 캐시 적중률을 달성함.
3. **[Invariant 3] 백그라운드 관리 잡 0ms/0토큰 바이패스**:
   - 제목 짓기, 캐치업, 체크포인트 등 IDE 자체 유지보수 프롬프트는 벡터 검색 호출 전에 즉시 `None`으로 바이패스하여 50ms 샌드박스 연산 및 토큰 주입을 0으로 차단함.

---

## 3. 상세 구현 명세 (Implementation Specification)

### 3.1 `MemoryPrefetcher.fetch_associated_context()` 바이패스 확장
* 파일: `src/tierbridge/memory_prefetcher.py`
* 변경 내용:
  ```python
  # IDE 내부 보조/백그라운드 관리 작업 질의 제외 (Bypass: 불필요한 연산 및 토큰 낭비 방지)
  ide_internal_keywords = [
      "generate a concise, single-line task title",
      "write a brief catch-up for a user",
      "you are performing a context checkpoint",
      "summarize the conversation",
      "title of the conversation",
      "recap the conversation"
  ]
  if any(kw in p_lower for kw in ide_internal_keywords):
      return None
  ```

### 3.2 `harness.py` 메모리 주입 위치 리팩토링 (캐시 보존형)
* 파일: `harness.py`
* 기존 방식 (Prefix Destructive):
  ```python
  if recalled_context:
      unified_req.messages.insert(0, Message(role="system", content=recalled_context))
  ```
* 개선 방식 (Cache Preserving):
  ```python
  if recalled_context:
      if unified_req and hasattr(unified_req, "messages") and unified_req.messages:
          # messages[-1]이 user 메시지인 경우 본문 하단에 Soft Reference 블록 첨부
          last_msg = unified_req.messages[-1]
          if last_msg.role == "user":
              last_msg.content = f"{last_msg.content}\n\n---\n{recalled_context}"
          else:
              # 비정형 메시지 구조 fallback: 시스템 프롬프트 뒤(인덱스 1)에 주입하여 messages[0] 프리픽스 해시 보존
              insert_idx = 1 if len(unified_req.messages) > 1 else 0
              unified_req.messages.insert(insert_idx, Message(role="system", content=recalled_context))
  ```

---

## 4. 검증 및 테스트 계획 (Verification Plan)

1. **단위 테스트 (`test_memory_prefetcher.py`)**:
   - `Generate a concise, single-line task title` 등 백그라운드 프롬프트 인입 시 `fetch_associated_context`가 `None`을 반환하는지 검증.
   - 정상 유저 도메인 질의 시 정상적으로 마크다운 블록이 반환되는지 검증.
2. **하네스 통합 테스트 (`test_system_directive.py`, `test_memory_handler.py`)**:
   - `messages[0]`의 시스템 프롬프트가 밀리지 않고 그대로 유지되는지 검증.
   - `messages[-1]`(유저 프롬프트)에 `recalled_context`가 정상 병합되는지 확인.
3. **전체 테스트 스위트 통과 검증**:
   - 25개 전체 유닛 테스트 회귀 여부 전수 확인.

---

## 5. 배포 정책 준수 (Deployment Policy)
- **사용자 특별 지침**: *"지금 티어브릿지 실행중이고 세션이 동작중인상태이기 때문에 배포는 내가 직접 할께, 보완만 진행."*
- **조치 방침**: `./deploy.sh`를 절대로 자동 실행하지 않으며, 코드 수정, 테스트, Git 커밋 및 푸시까지만 완료한 후 사용자에게 보고함.
