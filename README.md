# TierBridge

이 저장소는 Codex/ChatGPT 요청을 로컬 프록시로 받아서, 질문 난이도에 따라 모델과 추론 수준을 분류해 전달하는 하네스입니다.

## 목적

- 단순한 작업은 낮은 비용 경로로 보냅니다.
- 중간 난이도 작업은 `LUNA:MEDIUM` 또는 `TERRA:MEDIUM`으로 구분합니다.
- 고난도 작업만 상위 추론 단계로 보냅니다.
- 로컬 인증 정보는 `~/.codex/auth.json`에서 자동으로 읽습니다.

## 핵심 강점 및 특징 (Key Strengths)

- **Zero-Code Agent Modification (에이전트 무손상 구동)**:
  * 에이전트 CLI 내부 코드나 설정을 전혀 수정할 필요가 없습니다. 
  * 환경 변수 가로채기(`OPENAI_BASE_URL` 등)를 통해 투명하게 작동하므로, 에이전트 고유의 프롬프트 흐름이나 툴 사용(MCP) 제어 로직을 100% 무손상 상태로 이식합니다.
- **Seamless Session Continuation (세션 컨텍스트 완벽 보존)**:
  * 하네스가 매 스텝마다 실시간으로 모델 ID를 교체(예: `gpt-5.4-mini` ➔ `gpt-5.6-terra`)하여 릴레이하더라도, 백엔드 레벨에서 동일한 대화 세션 ID(`conversation_id`)와 이전 누적 대화 기록이 고스란히 전송됩니다.
  * 이로 인해 모델 변경으로 인한 기억 단절이나 컨텍스트가 꼬이는 부작용 없이, AI가 앞선 스텝에서 수행한 작업 흐름을 완벽히 이해하고 대화를 이어갑니다.
- **동적 비용 효율성 극대화**:
  * 컨텍스트를 안전하게 보존하면서 단순 질문은 저비용(`MINI`)으로, 복잡한 설계/디버깅 단계는 고성능(`TERRA`) 모델로 실시간 오토 스케일링함으로써 극대화된 크레딧 보존율을 제공합니다.

## 구성

- `harness.py` : 프록시 엔트리포인트 (요청 수신 및 응답 라우팅 릴레이)
- `src/tierbridge/` : 라우팅 및 연동 비즈니스 로직 패키지
  - `router.py` : 질문 난이도 평가(`gpt-5.6-luna` low effort 분류기 연동) 및 모델/추론 등급 결정
  - `stream_transpiler.py` : 이종 벤더 간의 실시간 스트리밍 포맷 트랜스파일러
  - `usage_tracker.py` : 실시간 스트림 파싱 기반 세션 토큰 소모 통계 및 비용 추적기
- `test_client.py` : 라우팅 확인용 테스트 클라이언트
- `patch_auth.py` : 로컬 인증 파일 보정 스크립트
- `Controller/routing_harness.md` : 설계 설명서

## 동작 방식

1. 클라이언트가 `POST /v1/chat/completions` 또는 `POST /v1/responses`로 요청을 보냅니다.
2. 프록시가 `gpt-5.6-luna` (low effort)로 질문 난이도를 정밀 분류합니다.
3. 분류 결과에 따라 모델과 추론 수준을 결정합니다 (최저: `gpt-5.6-luna` low, 상한: `gpt-5.6-terra` extra_high).
4. 최종 요청을 엔터프라이즈 백엔드로 전달합니다.

## 등급 체계

- `LUNA:LOW` (최저 기본 / 폴백 등급)
- `LUNA:MEDIUM`
- `TERRA:MEDIUM`
- `TERRA:HIGH`
- `TERRA:EXTRA_HIGH` (상한 등급)

## 선택 예시

| 요청 예시 | 선택 레벨 | 모델 | 추론 수준 |
|---|---|---|---|
| `명령어 오타 수정 방안` | `LUNA:LOW` | `gpt-5.6-luna` | `low` |
| `파이썬에서 단순 정렬 알고리즘 작성해줘` | `LUNA:LOW` | `gpt-5.6-luna` | `low` |
| `기존 입력 검증 로직을 리팩토링하고 중복을 줄여줘` | `LUNA:MEDIUM` | `gpt-5.6-luna` | `medium` |
| `서비스 간 호출 흐름을 정리하고 중간 난이도 아키텍처 수정안을 제시해줘` | `TERRA:MEDIUM` | `gpt-5.6-terra` | `medium` |
| `복잡한 알고리즘과 다중 컴포넌트 구조를 함께 설계해줘` | `TERRA:HIGH` | `gpt-5.6-terra` | `high` |
| `사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘` | `TERRA:EXTRA_HIGH` | `gpt-5.6-terra` | `extra_high` |

## 실행 및 연동 (원스텝 자동화)

포트 충돌 해제, 프록시 구동, 로컬 인증 패치, 그리고 **환경 변수 자동 주입**까지 단 하나의 스크립트로 자동으로 해결할 수 있습니다. (기본 구동 시 자가 진단 테스트는 비활성화되어 쾌속 가동됩니다.)

```bash
source run_harness.sh
```

- 진단 자가 테스트를 포함하여 구동하려면 `--test` 옵션을 사용하거나 `RUN_TESTS=true`를 전달합니다:
  ```bash
  source run_harness.sh --test
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

- 분류 요청은 `gpt-5.6-luna` (low effort)를 사용합니다.
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

사용자마다 라우팅 민감도나 추론 깊이를 조정하고 싶을 경우, **`src/tierbridge/router.py`** 내의 아래 네 가지 포인트를 직접 수정하여 커스텀할 수 있습니다.

### 1. 분류기용 기본 모델 조정
분류 연산을 더 저렴하게 처리하거나 더 똑똑하게 판정하고 싶을 때 사용합니다.
* **수정 위치**: `src/tierbridge/router.py` -> `Router.classify_request` 함수 내부 `payload["model"]` (기본값: `"gpt-5.4-mini"`)

### 2. 라우팅 등급 분류 판정 프롬프트 (인스트럭션) 수정
분류 기준의 임계치(Threshold)를 수정해 특정 키워드가 들어왔을 때 등급 배치를 다르게 유도합니다.
* **수정 위치**: `src/tierbridge/router.py` -> `Router.classify_request` 함수 내부 `payload["instructions"]` 문자열
* **팁**: 예산을 절약하려면 "기본적으로 LUNA 등급 이하로 분류하고, 복잡한 알고리즘이나 최적화 요구 시에만 TERRA 등급을 준다"와 같은 보수적인 명령어를 강화해 줍니다.

### 3. 실제 물리 모델 매핑 수정
분류기가 도출한 판정 등급(`MINI`, `LUNA`, `TERRA`)에 따라 원격 실서버로 보낼 실제 물리 모델 ID를 맵핑합니다.
* **수정 위치**: `src/tierbridge/router.py` -> `Router.classify_request` 함수 내부의 모델 스왑 조건문 분기:
  ```python
  if "MINI" in verdict:
      return "MINI", "gpt-5.4-mini", "low"
  elif "LUNA:LOW" in verdict:
      return "LUNA:LOW", "gpt-5.6-luna", "low"
  # ... LUNA / TERRA 등급에 따른 물리 모델 ID 할당 분기
  ```

### 4. 추론 강도 (Reasoning Effort) 매핑 변경
각 등급에 할당될 실질적인 추론 시간/토큰 한도를 조정합니다.
* **수정 위치**: `src/tierbridge/router.py` -> `Router.classify_request` 함수 내부의 반환값 튜플의 3번째 인자 (`reasoning_effort` 매핑 값):
  *(예: LUNA 등급의 추론 강도를 더 높이거나 낮추고 싶을 때, 해당 분기의 3번째 인자 값을 `"low"`, `"medium"`, `"high"`, `"max"` 중 원하는 레벨로 변경합니다.)*

## 💡 동적 비용 최적화 메커니즘 (Dynamic Cost Optimization)

이 프록시 하네스는 사용자의 턴(Turn) 단위가 아닌, **에이전트가 내부적으로 쪼개어 날리는 스텝(Step) 단위의 개별 API 호출마다 실시간으로 등급을 판정**하여 비용을 절감합니다.

### 겉만 고난도인 단순 작업의 비용 절감 기전 예시
만약 사용자가 첫 질문에 겉으로만 거창한 키워드를 던졌으나, 실제 분석 결과 단순한 오타/세미콜론 누락 등의 가벼운 작업으로 판명될 경우 하네스는 다음과 같이 똑똑하게 대처합니다:

1. **1단계: 첫 질문 시점 (고성능 모델 배치)**
   * **사용자 질문**: *"대규모 동시성 분산 락(Lock) 이슈 해결 및 코드 오타 수정해줘"*
   * **하네스의 동작**: 텍스트 프롬프트의 겉모양을 판정하여 안전을 위해 상위 모델인 **`TERRA:MAX` (`gpt-5.6-terra`, `max`)**를 배치합니다. (이 단계에서는 분석 전이므로 불가피하게 고성능 브레인을 빌려 씁니다.)
2. **2단계: 에이전트의 코드 분석 단계 (상위 모델 유지)**
   * **에이전트의 분석**: `TERRA` 모델의 고추론 능력을 빌려 프로젝트 코드를 훑어본 후, 이 분산 락 에러의 원인이 단순히 config 설정 파일 내 타임아웃 초단위 수치 오타(`3000`초 ➔ `3`초) 때문임을 완벽히 파악합니다.
3. **3단계: 실제 오타 수정 및 빌드 단계 (저비용 단순 태스크로 자동 강하 🚀)**
   * **에이전트의 요청**: *"config.properties 파일의 `lock.timeout=3000`을 `lock.timeout=3`으로 수정해주고 빌드 명령을 알려줘."*
   * **하네스의 동작**: 수정 및 빌드를 제안하는 새로운 구체적인 스텝 텍스트 프롬프트를 다시 떼어내어 난이도를 즉시 재판정합니다.
   * **결과**: 가벼운 파일 교체 및 단순 명령어 조회이므로 즉시 **`MINI` (`gpt-5.4-mini`, `low`)** 등급으로 강하 분류하여 3단계 이후의 수많은 테스트 및 수정 과정에 소모될 막대한 토큰 비용을 최소화합니다.
