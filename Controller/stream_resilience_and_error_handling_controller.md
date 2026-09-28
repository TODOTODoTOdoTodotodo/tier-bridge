# Proxy Stream Resilience & Error Handling Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
OpenAI 등 업스트림 LLM 백엔드 API에서 사용량 한도 초과(`429 Too Many Requests`, `usage_limit_reached`)나 인증 만료(`401 Unauthorized`), 서버 에러(`5xx`)가 반환될 때, 하네스 프록시(`harness.py`)의 스트리밍 제너레이터가 미처리 예외(`httpx.HTTPStatusError`)를 상위로 재전파하여 발생하는 **ASGI 애플리케이션 충돌(`ERROR: Exception in ASGI application`) 및 터미널 트레이스백 도배 현상**을 원천 차단합니다.

클라이언트(Codex CLI / Antigravity)에게 업스트림 원본 에러 메시지를 규격화된 SSE 이벤트로 안전하게 전달하고, 서버 프로세스는 오류 로그 없이 클린하게 스트림을 종료하는 무중단 고가용성 스트리밍 파이프라인을 구축합니다.

---

## 2. 근본 원인 분석 (Root Cause Analysis)

### 2.1 `stream_generator()` 내 `raise_for_status()` 호출 결함
- `harness.py`의 `stream_generator()`에서 업스트림 백엔드 응답이 200이 아닐 경우:
  ```python
  if upstream_res.status_code != 200:
      error_body = await upstream_res.aread()
      upstream_res.raise_for_status()  # ➔ httpx.HTTPStatusError 발생
  ```
- 이미 HTTP 응답 스트림이 열린 상태에서 제너레이터 내부에서 예외를 던지면, Starlette/FastAPI의 `StreamingResponse`가 이를 처리하지 못하고 ASGI 레벨에서 충돌을 일으킴.

### 2.2 제너레이터 예외 재전파(`raise`) 결함
- `except BaseException as e:` 블록에서 에러 메시지를 yield한 직후 `raise`를 실행:
  ```python
  except BaseException as e:
      ...
      yield f"data: {err_msg}\n\n".encode("utf-8")
      raise  # ➔ uvicorn ASGI Application Exception 발생 원인
  ```
- 제너레이터가 정상 종료(`return`)되지 않고 예외로 터져 나가면서 uvicorn이 매번 30~50줄의 ASGI 에러 트레이스백을 `harness.log`에 기록함.

---

## 3. 상세 개선 명세 (Detailed Architecture & Specifications)

### 3.1 비정상 상태 코드(Non-200) 클린 포워딩 규격
1. **`raise_for_status()` 전면 제거**:
   - 업스트림 상태 코드가 200이 아닌 경우(400, 401, 429, 500 등), 예외를 발생시키지 않고 업스트림 에러 본문(`error_body`)을 읽어 경고 로그만 기록함.
2. **클라이언트에 안전한 에러 전파**:
   - **바이패스 모드 (`is_passthrough == True`)**:
     업스트림의 원본 바이너리 에러 바디를 클라이언트에 그대로 `yield error_body` 하고 종료.
   - **SSE 변환 모드 (`is_passthrough == False`)**:
     업스트림 에러 JSON을 SSE 이벤트(`f"data: {err_text}\n\n"`) 및 완료 신호(`data: [DONE]\n\n`)로 전송한 후 안전하게 `return`.

### 3.2 스트림 제너레이터 예외 격리 규격
1. **클라이언트 취소 예외(`CancelledError`, `GeneratorExit`) 정상 수용**:
   - 클라이언트가 턴 도중 `Ctrl+C`나 세션 중단으로 연결을 끊는 경우 아무런 에러 없이 즉시 `return`.
2. **일반 런타임 예외 격리**:
   - 타임아웃, 소켓 단절 등 예상치 못한 통신 예외 발생 시, `[Error] Stream routing exception: {e}` 로그를 기록하고 클라이언트에 `proxy_error` SSE 이벤트를 yield한 뒤 정상 `return` 처리함 (절대 `raise` 재전파 금지).

### 3.3 안정적 자원 회수 및 사용량 수집
- `finally` 블록의 `trigger_tracking()`은 누적 버퍼(`accumulated_buffer`)가 존재할 때만 작동하므로, 에러 발생 시(버퍼 비어있음) 불필요한 사용량 수집이 유발되지 않음.

---

## 4. 검증 시나리오 (Verification Scenarios)
1. **429 Too Many Requests 인입 테스트**:
   - 백엔드가 429 (`usage_limit_reached`)를 반환할 때, `harness.log`에 `ERROR: Exception in ASGI application` 트레이스백이 발생하지 않고 `[Warning] Upstream API Error Status: 429` 경고만 1줄 기록되는지 검증.
2. **클라이언트 에러 수신 검증**:
   - 클라이언트가 연결 단절(Broken Connection) 없이 OpenAI 원본 에러 JSON을 정상 수신하는지 확인.
3. **무중단 프로세스 검증**:
   - 반복적인 429/401 응답 발생 후에도 프록시 프로세스(PID)가 죽지 않고 후속 정상 요청을 원활히 처리하는지 검증.
