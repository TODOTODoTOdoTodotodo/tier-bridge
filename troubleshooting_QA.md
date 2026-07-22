# 🛠️ TierBridge 설정 및 트러블슈팅 QA 가이드

이 문서는 하네스 프록시 서버(`tier-bridge`)를 구축, 연동 및 운영하는 과정에서 직면했던 핵심적인 트러블슈팅 사례들과 기술적 원인, 해결책들을 정리한 QA 문서입니다.

---

## 📋 목차
1. [Q1. 스트림 종료 경고 및 토큰 집계 누락 현상](#q1-스트림-종료-경고-및-토큰-집계-누락-현상)
2. [Q2. Invalid value: 'input_text' 400 Bad Request 에러](#q2-invalid-value-input_text-400-bad-request-에러)
3. [Q3. 모든 분석 요청이 MINI 모델로만 고정(디폴트)되어 처리되는 현상](#q3-모든-분석-요청이-mini-모델로만-고정디폴트되어-처리되는-현상)
4. [Q4. Classifier connection error: (ReadTimeout) 발생 및 지연 현상](#q4-classifier-connection-error-readtimeout-발생-및-지연-현상)
5. [Q5. 새 터미널을 열면 "No running Ollama server detected" 에러가 발생합니다](#q5-새-터미널을-열면-no-running-ollama-server-detected-에러가-발생합니다)
6. [Q6. lsof 시 18080 포트에 프로세스가 2개 뜨거나 ESTABLISHED 상태 소켓이 2개 생깁니다](#q6-lsof-시-18080-포트에-프로세스가-2개-뜨거나-established-상태-소켓이-2개-생깁니다)

---

### Q1. 스트림 종료 경고 및 토큰 집계 누락 현상
> **증상**: 로그에 에러는 없으나 `stream disconnected before completion: stream closed before response.completed` 경고가 뜨며 토큰 사용량 통계가 누락됩니다.

* **원인**: 
  * ChatGPT responses API는 본문 텍스트 생성이 완료(`is_done`)된 후에도, 스트림의 최하단 끝단에 토큰 소모량(`usage`)과 세션 종결 정보가 담긴 **`response.completed` 메타데이터 SSE 이벤트**를 덧붙여 전송합니다.
  * 기존 변환기(`StreamTranspiler`)가 `is_done = True` 시그널을 보자마자 즉시 스트림 루프를 조기 이탈(`break`)하여 연결을 끊음으로써 메타데이터 수집이 실패했던 것입니다.
* **해결책**:
  * `StreamTranspiler` 내부의 조기 탈출 코드를 제거하고, 원본 스트림 소켓이 완전히 닫힐 때까지 대기하며 이벤트를 수집하도록 보정했습니다.
  * 더불어 `/v1/responses` 스펙 요청인 경우에는 변환기를 태우지 않고 **바이트 그대로 100% 바이패스(Pass-through)** 시켜 완료 청크가 원형 유실 없이 클라이언트에 릴레이되도록 완수했습니다.

---

### Q2. Invalid value: 'input_text' 400 Bad Request 에러
> **증상**: CLI 연동 시 `Invalid value: 'input_text'. Supported values are: 'output_text' and 'refusal'. (param: input[3].content[0])` 에러와 함께 스트림이 깨집니다.

* **원인**:
  * 에이전트 CLI가 `/responses` API를 쏠 때, `input` 배열에는 사용자 질문뿐만 아니라 **이전 대화 기록(AI가 답변했던 내용)**도 누적되어 유입됩니다.
  * 이때 AI가 대답했던 파트의 타입은 `"type": "output_text"`여야 하지만, 프록시 변환 로직이 역할을 분간하지 않고 강제로 일괄 `"type": "input_text"`로 재조립(Double conversion)하여 전송했기 때문에 백엔드 스펙 위반으로 400 에러를 뱉었습니다.
* **해결책**:
  * 클라이언트가 이미 `input`이 포함된 `responses` 규격으로 요청을 쏜 경우, 페이로드 재조립을 일절 거치지 않고 **원본 `input` 및 `instructions` 구조를 그대로 가져다 `final_payload`에 복원(Direct Restore)**하도록 구조를 수정해 에러를 원천 차단했습니다.

---

### Q3. 모든 분석 요청이 LUNA:LOW 모델로만 고정(디폴트)되어 처리되는 현상
> **증상**: 고난도 분석이나 리팩토링 요청을 보내도 등급 분류가 돌지 않고 계속 `LUNA:LOW` (`gpt-5.6-luna`, `low`) 로만 처리됩니다.

* **원인**:
  * 클라이언트가 `/v1/responses` API로 호출할 때는 요청 바디에 `messages` 키 대신 ChatGPT responses 스펙인 **`input`** 키를 담아 보냅니다.
  * 기존 `OpenAIAdapter.to_unified_request`는 오직 `"messages"` 키만 읽도록 설계되어 있어, `/responses` 호출이 오면 질문 텍스트를 아예 추출해내지 못했습니다 (`user_prompt = ""`).
  * 이로 인해 분류기가 등급 평가 동작을 생략하고 즉시 `LUNA:LOW`로 기본 안전 규격 폴백 반환을 수행했던 것입니다.
* **해결책**:
  * `"messages"`가 비어 있고 `"input"` 키가 존재하는 경우, `input` 배열 내부에 포장된 각 `input_text` 문자열들을 긁어모아 `UnifiedRequest.messages`로 온전하게 복원해 주는 파이프라인을 구축해 정상 판정을 복구했습니다.

---

### Q4. Classifier connection error: (ReadTimeout) 발생 및 지연 현상
> **증상**: 가끔씩 `[Warning] Classifier connection error: (ReadTimeout). Fallback to LUNA:LOW.` 경고가 뜨며 `LUNA:LOW`로 떨어집니다.

* **원인**:
  * 사용자의 ChatGPT Enterprise 웹 세션 토큰(`access_token`)이 만료되었거나, 일시적인 네트워크 병목이 생겼을 때, Cloudflare WAF(방화벽)는 에러를 즉시 뱉지 않고 **강제로 소켓 커넥션을 대기 보류(Holding)**시킵니다.
  * 이로 인해 분류기가 응답을 받지 못하고 행에 걸리게 되며, 기존의 25초 타임아웃은 터미널이 최대 25초간 함께 굳어버려 먹통이 되는 UX 지연을 초래했습니다.
* **해결책**:
  * 질문 난이도 평가 기능은 신속성이 생명이므로, 타임아웃 설정을 **`8.0`초(연결 5.0초)**로 대폭 축소하여 신속한 실패(Fail-fast)를 유도했습니다. 8초가 지연되면 터미널이 대기하지 않고 즉시 안전망인 `LUNA:LOW` 모델로 매핑해 넘깁니다.
  * *이 증상이 잦다면 웹브라우저에서 ChatGPT 로그아웃 후 다시 로그인하여 `~/.codex/auth.json` 자격증명을 갱신하는 것이 좋습니다.*

---

### Q5. 새 터미널을 열면 "No running Ollama server detected" 에러가 발생합니다
> **증상**: 에이전트를 가동한 터미널이 아닌, 다른 새 터미널 창을 열고 `codex --oss --local-provider=ollama`를 치면 Ollama 서버를 찾을 수 없다고 뜹니다.

* **원인**:
  * 하네스 실행 시 주입되는 환경 변수들(`OLLAMA_HOST=http://127.0.0.1:18080` 등)은 **`export` 명령을 때린 해당 터미널 탭(세션) 내에서만 격리되어 유효**하기 때문입니다.
  * 새 터미널은 해당 변수가 유실되어 디폴트인 `11434` 포트로 접속을 시도하기 때문에 에러가 납니다.
* **해결책**:
  * 새 터미널 창에서도 **`source run_harness.sh`**를 한 번 실행해 주면, 켜져 있는 서버와 충돌 없이 환경 변수만 깔끔하게 재주입됩니다.
  * 또는 매번 치는 것이 번거롭다면 macOS의 **`~/.zshrc`** 파일 맨 밑에 환경 변수를 영구 등록하여 사용 가능합니다.

---

### Q6. lsof 시 18080 포트에 프로세스가 2개 뜨거나 ESTABLISHED 상태 소켓이 2개 생깁니다
> **증상**: 포트를 점유 중인 프로세스나 수립된 소켓 접속 목록을 보면 항상 2개씩 짝지어 잡힙니다.

* **원인**:
  1. **Uvicorn Reloader 프로세스 (2개)**:
     * Uvicorn 서버를 `--reload` 옵션으로 켜면, 소스 파일 변경을 감시하는 **부모(Watcher)**와 실제 통신을 처리하는 **자식(Worker)** 프로세스가 생성되어 파일 디스크립터를 공유하므로 2개가 리스닝 상태로 보입니다. (지극히 정상)
  2. **ESTABLISHED 네트워크 커넥션 (2개)**:
     * 프록시가 가운데서 요청을 릴레이하므로, `[CLI ➔ Harness Proxy]` 연결 1개와 `[Harness Proxy ➔ 원격 API]` 연결 1개가 동시에 맺어져 2개의 ESTABLISHED 커넥션이 관찰되는 것은 네트워크 중계 구조상 정상적인 흐름입니다.
