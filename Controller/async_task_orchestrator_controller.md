# Signal-Based Asynchronous Task Orchestrator Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
현재 Harnex는 클라이언트(Codex CLI, 에이전트 등)와 LLM 백엔드 사이에서 동작하는 **1:1 동기형 지능형 라우팅 리버스 프록시**입니다. 단일 요청에 대해 난이도를 판정하고, 6단계 모델 티어로 다운스케일링하며, 장기 기억을 선행 주입하는 데 탁월한 성능을 발휘합니다.

그러나 대규모 피처 개발이나 대규모 리팩토링 시, 단일 세션이 모든 파일과 컴포넌트를 순차적으로 수정하는 방식은:
1. 에이전트 컨텍스트 창이 빌드/테스트 로그로 오염되는 문제(Context Pollution)
2. 서로 독립적인 모듈(예: Entity, API Controller, Unit Test, UI)을 직렬로 처리하여 발생하는 대기 시간(Wall-clock Latency) 지연
3. 복잡한 문제를 한 번에 해결하려다 발생하는 모델 추론 품질 저하(Hallucination & Regression)

를 유발합니다. 본 사양서는 Harnex가 **"신호 기반 비동기 하네스 작업 분할 오케스트레이터(Signal-Based Asynchronous Task Orchestrator)"**로 진화하기 위한 4대 핵심 컴포넌트, 신호 프로토콜 규격, 작업 격리 샌드박스, 그리고 단계별 작업지시서를 정의합니다.

---

## 2. 현행 아키텍처와 갭 분석 (As-Is vs To-Be Gap Analysis)

```
[ As-Is: 1:1 동기형 모델 라우팅 프록시 ]
Client (Codex) ──[ 단일 프롬프트 ]──► Harnex (18080) ──► 6-Tier Router ──► OpenAI / Gemini
                                    └─► Memory DB (50ms Pre-fetch)

[ To-Be: 신호 기반 비동기 하네스 작업 분할 오케스트레이터 ]
Client / User ──[ 대형 목표 지시 ]──► Harnex Task Orchestrator (18080)
                                          │
                   ┌──────────────────────┴──────────────────────┐
                   ▼                                             ▼
           [Task Decomposition]                          [Signal Bus & DAG]
           - Subtask A (Schema/DB)                       - Task State Machine
           - Subtask B (API Controller)                  - PENDING ➔ RUNNING ➔ DONE
           - Subtask C (Unit Tests)                      - Event Stream (SSE)
                   │
                   ▼ (Fork: Worktree Sandbox Isolation)
       ┌───────────┴───────────┐
       ▼                       ▼
  [Worker-1 (Bronze)]    [Worker-2 (Silver)]
  (Branch: task/sub-A)   (Branch: task/sub-B)
       │                       │
       └───────────┬───────────┘
                   ▼ (Signal: COMPLETED / diff_patch)
           [Join Barrier & Patch Merger]
           - Conflict Detection & Auto-Resolution
           - Final Memory Ingestion & Dashboard Sync
```

| 항목 | As-Is (현재 하넥스) | To-Be (신호 기반 비동기 오케스트레이터) |
| :--- | :--- | :--- |
| **작업 단위** | 단일 HTTP 요청 (`/v1/responses`, `/v1/chat/completions`) | 계층적 태스크 그래프 (Task DAG: Parent Task ➔ N개 Subtasks) |
| **실행 방식** | 1:1 동기 스트리밍 (Client 대기) | 비동기 분기-합류 (Fork-Join: 병렬 실행 후 신호 수거) |
| **작업 격리** | 단일 작업 디렉토리 공유 (파일 쓰기 충돌 위험) | Git Worktree 기반 격리 샌드박스 (워커별 독립 브랜치) |
| **통신 규격** | 대화형 텍스트 핑퐁 (Chatty LLM Handoff) | 구조화된 상태 시그널 (JSON/HTTP: `START`, `PROGRESS`, `DONE`, `FAIL`) |
| **모델 배분** | 단일 턴 단위 6-Tier 라우팅 | 서브태스크 난이도별 최적 모델 워커 배분 (비용/성능 극대화) |
| **관측성** | 턴 단위 토큰/크레딧/LOC 로그 집계 | 태스크 DAG 시각화, 워커 상태(Gantt), 패치 병합 상태 실시간 모니터링 |

---

## 3. 핵심 설계 명세 (Core Architecture Specifications)

### 3.1 태스크 분해 및 의존성 그래프 (`TaskDecomposer` & `TaskDAG`)
- **역할**: 대형 프롬프트 인입 시 작업을 상호 독립적인 서브태스크로 분할하고 실행 순서(DAG) 수립.
- **구조**:
  ```python
  class SubTask:
      task_id: str             # 고유 ID (예: task_a8f9)
      parent_id: str           # 부모 태스크 ID
      title: str               # 작업명 (예: "User Entity JPA 어노테이션 수정")
      instruction: str         # 워커에게 전달될 명확하고 독립적인 단일 프롬프트
      dependencies: List[str]  # 선행 완료되어야 할 task_id 목록
      assigned_tier: str       # BRONZE | SILVER | GOLD | PLATINUM
      state: TaskState         # PENDING | READY | RUNNING | COMPLETED | FAILED
  ```

### 3.2 작업 공간 격리 샌드박스 (`WorktreeSandboxManager`)
- **파일 충돌 원천 차단**: 여러 에이전트가 동시에 같은 저장소의 파일을 수정하면 `git index.lock` 및 코드 덮어쓰기 발생.
- **Git Worktree 활용**:
  1. 각 워커 실행 시 `git worktree add ~/.harnex/worktrees/{task_id} -b task/{task_id}` 실행.
  2. 워커는 독립된 폴더에서 코드 작성, 컴파일, 단위 테스트 수행.
  3. 완료 시 변경 diff 패치(`git diff main`)를 생성하여 신호와 함께 전송하고 worktree 안전 제거.

### 3.3 신호 프로토콜 (`SignalBus` & State Machine)
- **비대화형(Silent) 신호 규격**: 에이전트 간 불필요한 말(Chatter)을 없애고 오직 4대 상태 시그널만 발행:
  1. `SIGNAL_STARTED`: 워커 구동 및 대상 브랜치 격리 완료 알림.
  2. `SIGNAL_PROGRESS`: 진행 단계(예: "파일 분석 완료", "테스트 5/5 통과") 및 중간 LOC 보고.
  3. `SIGNAL_COMPLETED`: 작업 완료 신호 + 결과 요약(Markdown) + Diff Patch + 소모 토큰/크레딧.
  4. `SIGNAL_FAILED`: 오류 원인(Traceback, 테스트 실패 로그) 및 재시도 요청 신호.

### 3.4 합류 장벽 및 패치 병합기 (`JoinBarrier` & `PatchMerger`)
- **장벽 동기화 (Barrier Synchronization)**: 선행 의존 태스크들이 모두 `SIGNAL_COMPLETED`를 보고할 때까지 후속 태스크 대기.
- **원클릭 병합**: 각 서브태스크의 diff patch를 메인 브랜치에 안전 적용 (`git apply` 또는 `git merge`).
- **충돌 중재기 (Conflict Mediator)**: 충돌 발생 시 고난도 랭크(`GOLD`/`PLATINUM`) 모델이 3-way diff를 분석하여 자동 충돌 해소.

### 3.5 신규 REST API 규격
- `POST /v1/orchestrator/dispatch`: 신규 태스크 그래프 등록 및 실행 트리거.
- `GET /v1/orchestrator/tasks/{task_id}`: 태스크 진행 상태, 워커 현황, 로그 조회.
- `POST /v1/orchestrator/tasks/{task_id}/signal`: 워커가 하네스로 완료/진행 신호 전송.
- `GET /v1/orchestrator/events`: SSE 기반 실시간 태스크 상태 스트리밍.

---

## 4. 컴포넌트별 비정상 케이스(Abnormal Cases) 및 방어 아키텍처 (Defensive Engineering)

본 장은 분산 비동기 하네스 환경에서 발생 가능한 모든 비정상/장애 시나리오를 정의하고, 시스템의 견고성(Robustness)을 보장하는 방어 메커니즘을 규정합니다.

### 4.1 태스크 분해 및 의존성 그래프 (Task DAG & Decomposition)
| 이상 징후 (Abnormal Case) | 발생 원인 및 위험 | 방어 아키텍처 (Defensive Strategy) |
| :--- | :--- | :--- |
| **① 순환 의존성 (Circular Dependency)** | 태스크 A ➔ B ➔ A 상호 참조로 인한 영구 대기(Deadlock) | DAG 인입 시 **Kahn's Algorithm(위상 정렬)** 및 DFS 사이클 검증기 즉시 실행. 사이클 감지 시 즉각 `HTTP 400 Bad Request`와 함께 순환 경로(`A -> B -> A`) 반환 및 거부. |
| **② 고립 노드 및 유령 의존성 (Dangling Dependencies)** | 존재하지 않는 임의의 `task_id`를 의존 목록에 지정 | DAG 검증기(`TaskValidator`)에서 그래프 내 모든 노드의 참조 무결성(Referential Integrity) 전수 점검. 누락 노드 발견 시 사전 거부. |
| **③ 태스크 폭증 및 트리 심도 초과 (Subtask Explosion / DoS)** | LLM 환각으로 100개 이상의 미세 태스크 생성 또는 심도 과다 | 설정 파라미터(`max_subtasks`, `max_dag_depth`)로 Throttling. 한도 초과 시 단일 통합 태스크로 폴백하거나 등록 차단. |
| **④ 무의미/빈 지시문 (No-op / Empty Instruction)** | 프롬프트 추출 실패로 공백 문자만 포함된 태스크 생성 | 지시문 최소 길이(`min_instruction_length`) 검증 통과 실패 시 유효성 검증 에러 처리. |

### 4.2 작업 공간 격리 샌드박스 (Git Worktree Sandbox)
| 이상 징후 (Abnormal Case) | 발생 원인 및 위험 | 방어 아키텍처 (Defensive Strategy) |
| :--- | :--- | :--- |
| **① Git Lock 경합 충돌 (`index.lock`)** | 복수 워커가 동시 `git worktree add` 호출 시 git lock 충돌 | 인프로세스 비동기 뮤텍스(`asyncio.Lock`)로 Worktree 생성/삭제 연산 직렬화. OS 레벨 락 충돌 시 지수 백오프(`git_lock_retry_attempts`, `git_lock_retry_backoff_base_ms`) 재시도 후 안전 해제. |
| **② 비정상 종료 시 좀비 Worktree 및 디스크 고갈 (Zombie Worktree)** | 워커 프로세스 강제 종료(OOM/SIGKILL)로 고아 디렉토리 및 브랜치 누적 | 런타임 기동 시 자동 정리 루틴(`git worktree prune`) 수행. 각 Worktree에 TTL(`worktree_ttl_seconds`) 부여 후 초과분 자동 수거. 디스크 여유 공간(`min_disk_free_bytes`) 임계치 미달 시 신규 디스패치 일시 중지. |
| **③ 부모 브랜치 드리프트 (Base Branch Drift)** | 선행 태스크의 머지로 메인 브랜치가 전진했으나, 워커가 구버전 커밋 기반으로 작업 | 의존성이 있는 후속 태스크는 선행 태스크의 머지 커밋(Merge Commit)을 최신 Base로 하여 Worktree를 신규 체크아웃. |
| **④ 경로 조작 공격 (Path Traversal / Injection)** | `task_id`에 `../../` 또는 특수문자 삽입으로 시스템 파일 침범 | 정규식 화이트리스트(`^[a-zA-Z0-9_-]{4,32}$`) 검증 및 `os.path.realpath`가 허용된 Worktree 루트 하위인지 엄격 강제. |

### 4.3 신호 버스 및 워커 생명주기 (Signal Bus & Worker Lifecycle)
| 이상 징후 (Abnormal Case) | 발생 원인 및 위험 | 방어 아키텍처 (Defensive Strategy) |
| :--- | :--- | :--- |
| **① 워커 무응답/무한 루프 (Silent Worker Hang)** | 툴 호출 대기 또는 네트워크 블로킹으로 신호 미전송 | 주기적 하트비트 감시(`worker_heartbeat_timeout_seconds`) + 하드 타임아웃(`task_timeout_seconds`) 적용. 초과 시 프로세스 트리 SIGTERM ➔ SIGKILL 강제 종료 후 `SIGNAL_FAILED (TIMEOUT)` 자동 트리거. |
| **② 역순/중복 신호 수신 (Out-of-Order / Duplicate Signals)** | 네트워크 지연으로 이미 `COMPLETED`된 태스크에 `PROGRESS` 인입 | 엄격한 상태 전이 행렬(State Transition Matrix) 적용. `COMPLETED`/`FAILED`는 터미널(Terminal) 상태로 규정하여 이후 인입되는 상태 변경 신호는 무시(Idempotent no-op). |
| **③ 거대 패치 폭탄 (Diff Payload Bomb / OOM)** | `node_modules`나 바이너리 수정으로 수백 MB diff 발생 | 패치 크기 상한(`max_patch_size_bytes`, 기본 5MB) 초과 시 패치 거부 및 태스크를 `FAILED_PAYLOAD_TOO_LARGE`로 전환. `.gitignore` 패턴 자동 배제 강제. |
| **④ 프로세스 크래시 (Silent Crash / Exit Code Non-Zero)** | 세그폴트나 OOM으로 신호 없이 프로세스 즉사 | 서브프로세스 감시 코루틴(`process.wait()`)에서 비정상 exit code 감지 시 `SIGNAL_FAILED (EXIT_CODE_N)`을 버스에 자동 주입. |

### 4.4 합류 장벽 및 패치 병합기 (Join Barrier & Patch Merger)
| 이상 징후 (Abnormal Case) | 발생 원인 및 위험 | 방어 아키텍처 (Defensive Strategy) |
| :--- | :--- | :--- |
| **① 연쇄 실패 방지 (Cascade Cancellation)** | 태스크 A 실패 시 A에 의존하는 B, C의 무의미한 자원 낭비 | 장애 격리 정책(`failure_policy: CONTINUE_INDEPENDENT`): 실패 노드의 하위 의존 태스크는 즉각 `CANCELLED` 처리하되, 독립적인 타 브랜치 서브태스크는 정상 완수. |
| **② Git 병합 충돌 (Merge Conflict)** | 서로 다른 워커가 동일 파일의 인접 영역을 수정하여 충돌 발생 | 1단계: `git apply --3way` 자동 시도.<br>2단계: 실패 시 `conflict_resolution_tier`(예: `PLATINUM`) 모델을 호출하여 3-way conflict hunk 자동 화해(Reconciliation) 시도.<br>3단계: 해결 불가 시 `git reset` 롤백 및 태스크를 `FAILED_CONFLICT`로 마킹하여 메인 오염 방지. |
| **③ 더티 메인 워킹 트리 (Dirty Main Tree)** | 사용자가 커밋하지 않은 로컬 수정본이 존재하는 상태에서 패치 인입 | 패치 머지 전 `git status --porcelain` 점검. 변경사항 발견 시 자동 임시 stash(`git stash create`) 생성 후 적용하거나 안전 중단(Abort with clean guidance). |

### 4.5 API 및 SSE 이벤트 백프레셔 (API & Backpressure)
| 이상 징후 (Abnormal Case) | 발생 원인 및 위험 | 방어 아키텍처 (Defensive Strategy) |
| :--- | :--- | :--- |
| **① 브라우저/클라이언트 단절 누수 (Broken Pipe)** | 사용자가 대시보드 탭을 닫아도 SSE 연결 유지로 메모리 누수 | `asyncio.CancelledError` 및 클라이언트 연결 종료 예외 핸들링을 통해 이벤트 버스 구독자 풀에서 즉각 안전 등록 해제. |
| **② 이벤트 버퍼 오버플로우 (Event Buffer Overflow)** | 수많은 워커가 초당 수십 개의 progress 신호를 쏟아낼 때 메모리 폭증 | `asyncio.Queue(maxsize=sse_buffer_size)`를 적용하고 유실 방지용 Ring Buffer(최근 N개 이벤트 보존)로 백프레셔 제어. |

---

## 5. 제로 하드코딩 설정 아키텍처 (Zero-Hardcoding Configuration Spec)

모든 임계치, 경로, 재시도 횟수, 모델 티어는 코드에 직접 상수로 박아두지 않으며, **설정 파일 (`config/orchestrator_config.json`)** 및 **환경 변수 (`HARNEX_ORCH_*`)**를 통해 100% 외부 주입 및 동적 오버라이드 가능하도록 구현합니다.

### 5.1 설정 탐색 우선순위 (Configuration Precedence)
1. **1순위 (최우선)**: 실행 시 지정된 CLI 옵션 또는 런타임 환경 변수 (`HARNEX_ORCH_<KEY>`)
2. **2순위**: 외부 설정 파일 (`config/orchestrator_config.json`)
3. **3순위**: Pydantic / dataclass 기반 내장 기본값 (`OrchestratorConfig`)

### 5.2 전체 설정 파라미터 매핑표
| JSON 설정 키 | 환경 변수명 | 기본값 | 단위 / 설명 |
| :--- | :--- | :---: | :--- |
| `max_subtasks` | `HARNEX_ORCH_MAX_SUBTASKS` | `20` | DAG 당 최대 허용 서브태스크 개수 |
| `max_dag_depth` | `HARNEX_ORCH_MAX_DAG_DEPTH` | `5` | 태스크 의존성 트리의 최대 허용 심도 |
| `min_instruction_length` | `HARNEX_ORCH_MIN_INSTRUCTION_LENGTH` | `5` | 서브태스크 지시문 최소 글자 수 |
| `task_timeout_seconds` | `HARNEX_ORCH_TASK_TIMEOUT_SECONDS` | `600` | 개별 태스크 최대 실행 제한 시간 (초) |
| `worker_heartbeat_interval_seconds` | `HARNEX_ORCH_WORKER_HEARTBEAT_INTERVAL` | `30` | 워커 하트비트 전송 주기 (초) |
| `worker_heartbeat_timeout_seconds` | `HARNEX_ORCH_WORKER_HEARTBEAT_TIMEOUT` | `90` | 하트비트 미수신 시 좀비 판정 임계 시간 (초) |
| `max_patch_size_bytes` | `HARNEX_ORCH_MAX_PATCH_SIZE_BYTES` | `5242880` | diff 패치 페이로드 최대 허용 바이트 (5MB) |
| `worktree_root` | `HARNEX_ORCH_WORKTREE_ROOT` | `~/.harnex/worktrees` | 격리 샌드박스 작업 디렉토리 루트 |
| `worktree_ttl_seconds` | `HARNEX_ORCH_WORKTREE_TTL_SECONDS` | `3600` | 방치된 고아 Worktree 강제 회수 TTL (초) |
| `min_disk_free_bytes` | `HARNEX_ORCH_MIN_DISK_FREE_BYTES` | `1073741824` | 샌드박스 생성에 필요한 최소 디스크 여유 공간 (1GB) |
| `git_lock_retry_attempts` | `HARNEX_ORCH_GIT_LOCK_RETRY_ATTEMPTS` | `5` | Git Lock 경합 시 최대 재시도 횟수 |
| `git_lock_retry_backoff_base_ms` | `HARNEX_ORCH_GIT_LOCK_BACKOFF_MS` | `200` | Git Lock 지수 백오프 기본 대기 밀리초 |
| `max_merge_retries` | `HARNEX_ORCH_MAX_MERGE_RETRIES` | `2` | 패치 머지 실패 시 최대 재시도 횟수 |
| `failure_policy` | `HARNEX_ORCH_FAILURE_POLICY` | `CONTINUE_INDEPENDENT` | `FAIL_FAST` 또는 `CONTINUE_INDEPENDENT` |
| `conflict_resolution_tier` | `HARNEX_ORCH_CONFLICT_RESOLUTION_TIER` | `PLATINUM` | 3-way 충돌 자동 해소에 투입할 모델 티어 |
| `sse_buffer_size` | `HARNEX_ORCH_SSE_BUFFER_SIZE` | `1000` | 이벤트 스트리밍 버퍼 큐 최대 크기 |

---

## 6. 단계별 구현 작업지시서 (Implementation Work Directive)

### Phase 1: 설정 관리자 및 신호 프로토콜 엔진 구축
- [ ] `src/harnex/orchestrator/config.py`: `OrchestratorConfig` Pydantic 모델 및 환경변수/JSON 3단 캐스케이드 로더 구현.
- [ ] `src/harnex/orchestrator/models.py`: `TaskDAG`, `SubTask`, `TaskState`, `SignalMessage` 데이터 모델 및 사이클 검증기(`TaskValidator`) 정의.
- [ ] `src/harnex/orchestrator/signal_bus.py`: 인프로세스 Reactive 이벤트 버스, 상태 전이 불변식 행렬, 하트비트 모니터링 엔진 구현.
- [ ] `test_orchestrator_signal_bus.py`: 사이클 감지, 역순 신호 억제, 타임아웃 감시, 하드코딩 배제 설정 로딩 단위 테스트.

### Phase 2: Git Worktree 샌드박스 및 워커 풀 구현
- [ ] `src/harnex/orchestrator/sandbox.py`: 뮤텍스 락 기반 `git worktree` 자동 생성/삭제, TTL 가비지 컬렉터, 경로 트래버설 방어자 구현.
- [ ] `src/harnex/orchestrator/worker_pool.py`: 프로세스 기반 비동기 서브프로세스 워커 풀, 크래시 감지기, diff 크기 캡핑 필터 탑재.
- [ ] `test_orchestrator_sandbox.py`: Git lock 경합 시뮬레이션, 좀비 워크트리 회수, 경로 탈출 시도 방어 검증 테스트.

### Phase 3: DAG 스케줄러 & 합류 장벽 (Join Barrier)
- [ ] `src/harnex/orchestrator/scheduler.py`: 위상 정렬 기반 비동기 스케줄러. 선행 의존성 해소 태스크 디스패치 및 연쇄 실패 격리(`failure_policy`) 구현.
- [ ] `src/harnex/orchestrator/barrier.py`: 완료 신호 취합, 3-way diff 병합, 모델 기반 자동 충돌 중재기(`ConflictResolver`), 더티 트리 감지기 구현.
- [ ] `test_orchestrator_scheduler.py`: 3개 병렬/직렬 복합 DAG 파이프라인 E2E 시뮬레이션 및 충돌 자동 해소 검증.

### Phase 4: Harnex API 라우팅 및 CLI 통합 (`harnex-task`)
- [ ] `harness.py`: `/v1/orchestrator/*` 엔드포인트 및 SSE 연결 단절 방어 로직 등록.
- [ ] `src/harnex/orchestrator/cli.py`: 터미널 전용 태스크 디스패처 및 진행률 모니터링 CLI.
- [ ] `deploy.sh`: `~/.local/bin/harnex-task` 바이너리 생성 및 터미널 Alias 등록.

### Phase 5: 실시간 대시보드 시각화 연동
- [ ] `usage_dashboard.html`: 상단 신규 탭 `[🧩 오케스트레이터 (Tasks)]` 추가.
- [ ] Mermaid/D3 기반 실시간 Task DAG 렌더링 (노드 상태별 색상 점멸: 대기/실행중/성공/실패) 및 워커별 크레딧·LOC 프로파일링 뷰어 탑재.

---

## 7. 불변식 및 설계 제약 (Design Invariants & Constraints)

1. **Zero Hardcoding**: 시스템 내 모든 시간, 크기, 임계치, 경로는 `OrchestratorConfig` 객체를 거쳐야 하며 코드 내 매직 넘버나 리터럴 문자열 하드코딩을 엄격히 금지한다.
2. **Zero-Poll Event Driven**: 상위 오케스트레이터는 워커의 상태를 루프로 폴링하지 않으며, 워커가 방출하는 HTTP/Signal Webhook 이벤트에 의해서만 깨어나 동작한다 (Reactive Wakeup).
3. **Strict Isolation**: 워커는 메인 작업 디렉토리에 직접 쓰기 작업을 수행할 수 없으며, 반드시 자신에게 할당된 Worktree 샌드박스 내에서만 파일 I/O를 수행해야 한다.
4. **Idempotent Transitions**: 이미 완료(`COMPLETED`)되거나 취소/실패(`FAILED`/`CANCELLED`)된 태스크의 상태는 사후 신호에 의해 절대 변경되지 않는다.
5. **Documentation First**: 모든 신규 모듈 및 인터페이스 변경은 본 컨트롤러 사양서를 기준으로 동기화된다.
