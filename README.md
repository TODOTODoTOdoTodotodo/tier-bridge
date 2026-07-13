# TierBridge

이 저장소는 Codex/ChatGPT 요청을 로컬 프록시로 받아서, 질문 난이도에 따라 모델과 추론 수준을 분류해 전달하는 하네스입니다.

## 목적

- 단순한 작업은 낮은 비용 경로로 보냅니다.
- 중간 난이도 작업은 `LUNA:MEDIUM` 또는 `TERRA:MEDIUM`으로 구분합니다.
- 고난도 작업만 상위 추론 단계로 보냅니다.
- 로컬 인증 정보는 `~/.codex/auth.json`에서 자동으로 읽습니다.

## 구성

- `harness.py` : FastAPI 프록시 서버
- `test_client.py` : 라우팅 확인용 테스트 클라이언트
- `patch_auth.py` : 로컬 인증 파일 보정 스크립트
- `Controller/routing_harness.md` : 설계 설명서

## 동작 방식

1. 클라이언트가 `POST /v1/chat/completions` 또는 `POST /v1/responses`로 요청을 보냅니다.
2. 프록시가 질문을 분류합니다.
3. 분류 결과에 따라 모델과 추론 수준을 선택합니다.
4. 최종 요청을 엔터프라이즈 백엔드로 전달합니다.

## 등급 체계

- `MINI`
- `LUNA:LOW`
- `LUNA:MEDIUM`
- `TERRA:MEDIUM`
- `TERRA:HIGH`
- `TERRA:EXTRA_HIGH`
- `TERRA:MAX`

## 선택 예시

| 요청 예시 | 선택 레벨 | 모델 | 추론 수준 |
|---|---|---|---|
| `명령어 오타 수정 방안` | `MINI` | `gpt-5.4-mini` | `low` |
| `파이썬에서 단순 정렬 알고리즘 작성해줘` | `LUNA:LOW` | `gpt-5.6-luna` | `low` |
| `기존 입력 검증 로직을 리팩토링하고 중복을 줄여줘` | `LUNA:MEDIUM` | `gpt-5.6-luna` | `medium` |
| `서비스 간 호출 흐름을 정리하고 중간 난이도 아키텍처 수정안을 제시해줘` | `TERRA:MEDIUM` | `gpt-5.6-terra` | `medium` |
| `복잡한 알고리즘과 다중 컴포넌트 구조를 함께 설계해줘` | `TERRA:HIGH` | `gpt-5.6-terra` | `high` |
| `사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘` | `TERRA:EXTRA_HIGH` | `gpt-5.6-terra` | `extra_high` |
| `대규모 동시성 분산 락(Lock) 이슈 해결 방안 설계해줘` | `TERRA:MAX` | `gpt-5.6-terra` | `max` |

## 실행 및 연동 (원스텝 자동화)

포트 충돌 해제, 프록시 구동, 자가 진단 테스트, 로컬 인증 패치, 그리고 **환경 변수 자동 주입**까지 단 하나의 스크립트로 자동으로 해결할 수 있습니다.

실행 시 `run_harness.sh`가 `.venv`를 자동 생성하고 `requirements.txt`에 정의된 Python 패키지들을 설치합니다. 따라서 별도 수동 설치 없이도 시작할 수 있습니다.

```bash
source run_harness.sh
```

`source` 명령어를 사용해 실행하면 실행 완료 시 환경 변수 4개(`OPENAI_BASE_URL`, `CODEX_API_BASE`, `OLLAMA_HOST`, `CODEX_OSS_PORT`)가 현재 터미널 세션에 자동으로 즉시 주입됩니다. 수동 복사 필요 없이 즉시 `codex --oss --local-provider=ollama`를 입력하고 뒤에 원하는 명령(예: `chat`, `explain` 등)을 붙여서 실행하시면 됩니다.

### 수동 실행 (상세)

만약 수동으로 한 단계씩 제어하고 싶다면 아래 명령어를 사용합니다.

#### 1. 서버 개별 실행
```bash
./.venv/bin/python -m uvicorn harness:app --host 0.0.0.0 --port 18080 --reload
```

#### 2. 등급 판정 자가 테스트
```bash
./.venv/bin/python test_client.py decision
```

#### 3. 일반 스트리밍 릴레이 테스트
```bash
./.venv/bin/python test_client.py
```

## 실시간 프록시 로그 확인 방법

원스텝 가동 스크립트(`source run_harness.sh`)를 실행하면 서버의 세부 로그가 백그라운드로 전환되어 `harness.log`에 실시간으로 기록됩니다. 
등급 판정 결과와 원격 실서버 통신 로그를 모니터링하려면 터미널 창을 하나 더 열어 아래 명령어를 실행하십시오:

```bash
tail -f harness.log
```

*(여기서 실시간으로 결정되는 `➔ [DECISION]` 등급과 커넥션 상태를 바로 추적할 수 있습니다.)*

## 검증 메모

- 분류 요청은 `gpt-5.4-mini`를 사용합니다.
- `decision`은 서버 로그의 `➔ [DECISION]` 출력으로 확인하는 것이 가장 정확합니다.
- production 경로와 mock 경로 모두 등급별 `reasoning`을 반영합니다.

## 토큰 소모량 확인 방법

Codex CLI의 `status` 명령은 로컬 Ollama 모드에서 크레딧 정보를 표시하지 않습니다.
대신 프록시가 직접 업스트림 응답에서 토큰 소모량을 파싱하여 세션 단위로 누적합니다.

**실시간 로그 확인** (`harness.log`에서 요청마다 출력):
```
➔ [DECISION] 추정된 등급: TERRA:HIGH
➔ [USAGE] TERRA:HIGH (gpt-5.6-terra) | input=1024 output=512 tokens
```

**세션 전체 누적 사용량 조회** (별도 터미널에서):
```bash
curl http://localhost:18080/usage
```

응답 예시:
```json
{
  "session_summary": {
    "total_requests": 5,
    "total_input_tokens": 4210,
    "total_output_tokens": 1830,
    "total_tokens": 6040
  },
  "per_request_history": [
    { "model": "gpt-5.6-terra", "decision": "TERRA:HIGH", "effort": "high", "input_tokens": 1024, "output_tokens": 512 }
  ]
}
```



## 주의사항

- 이 저장소는 외부 MCP나 외부 스킬 연결을 전제로 하지 않습니다.
- 실제 엔터프라이즈 인증은 로컬 `auth.json`에 의존합니다.
- 비용 민감도가 높으므로, 분류 기준은 보수적으로 유지하는 편이 좋습니다.

## 🛠️ 커스터마이징 가이드 (Customization)

사용자마다 라우팅 민감도나 추론 깊이를 조정하고 싶을 경우, `harness.py` 내의 아래 네 가지 포인트를 직접 수정하여 커스텀할 수 있습니다.

### 1. 분류기용 기본 모델 조정
분류 연산을 더 저렴하게 처리하거나 더 똑똑하게 판정하고 싶을 때 사용합니다.
* **수정 위치**: `harness.py` -> `estimate_model_and_effort` 함수 내부 `payload["model"]` (기본값: `"gpt-5.4-mini"`)

### 2. 라우팅 등급 분류 판정 프롬프트 (인스트럭션) 수정
분류 기준의 임계치(Threshold)를 수정해 특정 키워드가 들어왔을 때 등급 배치를 다르게 유도합니다.
* **수정 위치**: `harness.py` -> `estimate_model_and_effort` 함수 내부 `payload["instructions"]` 문자열
* **팁**: 예산을 절약하려면 "기본적으로 LUNA 등급 이하로 분류하고, 복잡한 알고리즘이나 최적화 요구 시에만 TERRA 등급을 준다"와 같은 보수적인 명령어를 강화해 줍니다.

### 3. 실제 물리 모델 매핑 수정
분류기가 도출한 판정 등급(`MINI`, `LUNA`, `TERRA`)에 따라 원격 실서버로 보낼 실제 물리 모델 ID를 맵핑합니다.
* **수정 위치**: `harness.py` -> `route_harness` 함수 내부의 모델 스왑 조건문:
  ```python
  if decision == "MINI":
      body["model"] = "gpt-5.4-mini"
  elif decision.startswith("LUNA"):
      body["model"] = "gpt-5.6-luna"
  elif decision.startswith("TERRA"):
      body["model"] = "gpt-5.6-terra"
  ```

### 4. 추론 강도 (Reasoning Effort) 매핑 변경
각 등급에 할당될 실질적인 추론 시간/토큰 한도를 조정합니다.
* **수정 위치**: `harness.py` -> `route_harness` 함수 내부의 `decision_to_effort` 딕셔너리:
  ```python
  decision_to_effort = {
      "MINI": "low",
      "LUNA:LOW": "low",
      "LUNA:MEDIUM": "medium",
      "TERRA:MEDIUM": "medium",
      "TERRA:HIGH": "high",
      "TERRA:EXTRA_HIGH": "extra_high",
      "TERRA:MAX": "max",
  }
  ```
  *(예: LUNA 등급의 추론 강도를 더 높이거나 낮추고 싶을 때 해당 문자열 값을 `"none"`, `"low"`, `"medium"`, `"high"`, `"max"` 중 원하는 레벨로 변경합니다.)*
