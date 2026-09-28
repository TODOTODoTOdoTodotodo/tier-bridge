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

### 3.1 스트림 생성 전 상태 검사(Pre-dispatch Status Check) 규격
1. **문제점 분석 (`stream disconnected before completion: stream closed before response.completed`)**:
   - FastAPI/Starlette의 `StreamingResponse`는 인스턴스화 시점에 클라이언트에게 `HTTP/1.1 200 OK`와 `content-type: text/event-stream` 헤더를 먼저 전송함.
   - 만약 업스트림(OpenAI)이 `429 Too Many Requests` (`usage_limit_reached`)를 반환한 상태에서 제너레이터가 에러 바디를 yield하고 종료되면, 클라이언트의 SSE 파서는 "200 스트림인데 `response.completed` 이벤트 없이 스트림이 닫혔다"고 판단하여 오류를 발생시킴.
2. **사전 검사 및 HTTP 상태 코드 직결 전송**:
   - `StreamingResponse`를 생성하기 전에 `client.send(request, stream=True)`로 업스트림 응답 헤더를 먼저 수신.
   - `upstream_res.status_code != 200` (429, 401, 500 등)인 경우:
     - `StreamingResponse`를 생성하지 않음.
     - 업스트림 에러 본문(`error_body`)을 읽고 즉시 스트림을 닫은 뒤, 업스트림의 실제 HTTP 상태 코드와 `application/json` 타입으로 `Response(content=error_body, status_code=upstream_res.status_code)`를 직접 반환.
     - 클라이언트는 정상적인 `HTTP 429` 에러를 수신하여 크레딧 한도 초과/쿼터 소진 메시지를 정확히 인지하게 됨.
   - `upstream_res.status_code == 200`인 경우에만 `StreamingResponse`를 반환하여 안전하게 데이터 스트리밍 수행.

### 3.2 스트림 제너레이터 예외 격리 규격
1. **클라이언트 취소 예외(`CancelledError`, `GeneratorExit`) 정상 수용**:
   - 클라이언트가 턴 도중 `Ctrl+C`나 세션 중단으로 연결을 끊는 경우 아무런 에러 없이 즉시 `return`.
2. **일반 런타임 예외 격리**:
   - 타임아웃, 소켓 단절 등 예상치 못한 통신 예외 발생 시, `[Error] Stream routing exception: {e}` 로그를 기록하고 클라이언트에 `proxy_error` SSE 이벤트를 yield한 뒤 정상 `return` 처리함 (절대 `raise` 재전파 금지).

### 3.3 안정적 자원 회수 및 사용량 수집
- `finally` 블록에서 `await upstream_res.aclose()` 및 `await client.aclose()`를 호출하여 HTTP 커넥션 누수를 차단.
- `trigger_tracking()`은 누적 버퍼(`accumulated_buffer`)가 존재할 때만 작동하므로, 에러 발생 시(버퍼 비어있음) 불필요한 사용량 수집이 유발되지 않음.

---

## 4. 검증 시나리오 (Verification Scenarios)
1. **429 Too Many Requests 사전 차단 테스트**:
   - 업스트림이 429 (`usage_limit_reached`) 반환 시, 클라이언트에게 HTTP 200 SSE 스트림이 아닌 **HTTP 429 JSON 응답**이 반환되는지 검증.
   - `stream disconnected before completion` 파싱 에러가 발생하지 않는지 확인.
2. **클라이언트 에러 수신 검증**:
   - 클라이언트가 연결 단절(Broken Connection) 없이 OpenAI 원본 에러 JSON을 정상 수신하는지 확인.
3. **무중단 프로세스 검증**:
   - 반복적인 429/401 응답 발생 후에도 프록시 프로세스(PID)가 죽지 않고 후속 정상 요청을 원활히 처리하는지 검증.
