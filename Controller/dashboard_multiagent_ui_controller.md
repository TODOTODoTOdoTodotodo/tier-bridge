# Dashboard Multi-Agent & Task DAG UI Controller Specification

## 1. 개요 및 목적 (Background & Objectives)
Harnex 오케스트레이터의 신호 기반 비동기 멀티에이전트 태스크 분할 엔진이 도입됨에 따라, 웹 대시보드(`usage_dashboard.html` 및 `analyze_usage.py`)에 멀티에이전트 실행 현황, 태스크 의존성 그래프(DAG), 워커별 자원 소모량(LOC, Credit, Token) 및 실시간 상태를 시각화하는 전용 UI 컴포넌트를 설계합니다.

기존의 4대 탭(`[📊 사용량 현황]`, `[🧠 기억 저장소]`, `[🩹 모델 힐링팩터]`, `[📈 월별 결산 & 감사]`)의 동작과 레이아웃은 100% 보존하며, 다섯 번째 탭인 **`[🧩 멀티에이전트 (Tasks)]`**를 증설하여 단일 세션 프록시 모드와 멀티에이전트 모드가 완전한 병행(Coexistence)을 이루도록 합니다.

---

## 2. UI/UX 레이아웃 규격 (Fractal Design Language 연동)

### 2.1 신규 탭 내비게이션 (`#tabNavigation`)
- 탭 식별자: `data-tab="tasks"`
- 탭 버튼 명칭: `<i class="fa-solid fa-diagram-project mr-2"></i>멀티에이전트 (Tasks)`
- 뱃지 연동: 현재 실행 중인 활성 태스크 개수를 실시간 뱃지로 표출 (예: `2 RUNNING`).

### 2.2 메인 뷰포트 구성 (2-Row 그리드)
```
┌────────────────────────────────────────────────────────────────────────┐
│ [헤더 요약 카드 (4-Grid)]                                              │
│ 1. 총 태스크 수  2. 실행 중 워커 (Active)  3. 누적 생성 LOC  4. 절감 크레딧│
├───────────────────────────────────┬────────────────────────────────────┤
│ [좌측: Task DAG & 타임라인 뷰]    │ [우측: 워커 상태 & 신호 로그 스트림]│
│ - Mermaid / SVG 기반 의존성 트리  │ - 워커별 카드 (PID, Tier, 브랜치) │
│ - 노드 상태별 색상 점멸           │ - 자율 ReAct 턴 현황 (Turn N/M)   │
│   • PENDING: Slate Gray           │ - 실시간 인입 신호 (START/DONE)    │
│   • RUNNING: Amber Pulse          │ - Diff 미리보기 및 병합 상태       │
│   • COMPLETED: Emerald Green      │                                    │
│   • FAILED: Crimson Red           │                                    │
└───────────────────────────────────┴────────────────────────────────────┘
```

---

## 3. 데이터 모델 및 API 연동 규격

### 3.1 대시보드 통계 API 확장 (`GET /v1/dashboard/stats`)
기존 통계 응답 객체에 `orchestrator` 필드를 비파괴적으로 추가:
```json
{
  "total_records": 150,
  "total_credits": 245.5,
  "real_credits": 180.2,
  "orchestrator": {
    "enabled": true,
    "active_tasks_count": 1,
    "completed_tasks_count": 8,
    "failed_tasks_count": 0,
    "tasks": [
      {
        "task_id": "dag_20261021_01",
        "title": "사용자 인증 모듈 비동기 리팩토링",
        "state": "RUNNING",
        "created_at": "2026-10-21T16:50:00",
        "total_subtasks": 3,
        "completed_subtasks": 1,
        "subtasks": [
          {
            "subtask_id": "sub_auth_01",
            "title": "User Entity JPA 어노테이션 수정",
            "tier": "BRONZE",
            "state": "COMPLETED",
            "worker_pid": 71822,
            "worktree": "~/.harnex/worktrees/sub_auth_01",
            "turns": 3,
            "loc": 45,
            "credits": 0.08,
            "elapsed_seconds": 24
          },
          {
            "subtask_id": "sub_auth_02",
            "title": "AuthService 비즈니스 로직 작성",
            "tier": "SILVER",
            "state": "RUNNING",
            "worker_pid": 71825,
            "worktree": "~/.harnex/worktrees/sub_auth_02",
            "turns": 2,
            "loc": 120,
            "credits": 0.35,
            "elapsed_seconds": 45
          }
        ]
      }
    ]
  }
}
```

### 3.2 Zero-Flicker 라이브 동기화 정책
- 3초 주기 오토싱크(`#liveSyncBadge`) 폴링 시, DOM 전체를 파괴하지 않고 `task_id` 및 `subtask_id` 단위 In-Place DOM Diffing으로 카드 상태 및 프로그레스 바만 무깜빡임(Zero-Flicker) 갱신.
- 멀티에이전트 태스크 데이터가 없을 경우(0건): Fractal 스타일의 정갈한 Empty State 안내문구 표출 (*"현재 실행 중인 비동기 오케스트레이터 태스크가 없습니다. `harnex-task dispatch` 명령어로 병렬 태스크를 시작하세요."*).

---

## 4. 프론트엔드 방어 규격 (Defensive UI Invariants)
1. **타입 안전성 가드**: `stats.orchestrator`가 누락되거나 `null`이어도 기존 탭들이 깨지지 않도록 `const orch = stats.orchestrator || { enabled: false, tasks: [] };` 방어적 기본값 주입.
2. **XSS 방어**: 지시문 및 워커 로그 렌더링 시 반드시 `escapeHtml()` 함수를 거쳐 DOM에 삽입.
3. **Mermaid 렌더러 안전 가드**: 노드 제목에 괄호, 따옴표, 특수문자가 포함될 경우 Mermaid 구문 오류가 발생하므로 라벨을 항상 큰따옴표로 이스케이프(`id["Label"]`).
4. **인라인 `<script>` 태그 조기 종료 방어 (`_safe_json_embed`)**: 사용자 프롬프트 또는 메모리 기록에 `</script>` 문자열이 포함될 경우 브라우저 HTML 토크나이저가 인라인 `<script>` 태그를 중간에 강제 종료하는 표준 브라우저 취약점 방어. `json.dumps()` 후 `<`, `>`, `&`를 `\u003c`, `\u003e`, `\u0026`로 유니코드 이스케이프 변환하여 삽입.
5. **글로벌 스코프 함수 바인딩 (`window.*`)**: WebKit/Safari 환경(cmux 등)에서 인라인 `onclick` 핸들러 호출 누락을 방어하기 위해 `window.switchDashboardTab`, `window.switchTab`, `window.renderTasksView`를 전역 객체에 명시적 등록.
6. **단일책임원칙(SRP) 기반 UI 함수 분리**:
   - `renderTasksView`: DAG 카드 및 생각나무(Tree-of-Thought) 구조 렌더링에만 집중.
   - `renderMissionControlFeed`: 에이전트 발화, 사고 과정, 주입된 기억 피드 렌더링에만 집중.
   - `sendHumanIntervention`: 사용자 지시 개입 폼 검증 및 API 전송에만 집중.
   - `initAgentEventSource`: SSE 실시간 스트림 연결 및 자동 재연결에만 집중.

---

## 5. 생각나무형 기억 추적 및 비용 꼬리표 규격 (Tree-of-Thought & Cost Tag Spec)
1. **서브태스크 노드 생각나무 표출**:
   - 각 서브태스크 카드 상단에 `🧠 Injected Memory: [기억 노드명]` 뱃지를 표출하여 에이전트가 어떤 사내 지식을 바탕으로 작업 중인지 가시화.
   - 각 서브태스크 노드 우측에 실시간 비용 꼬리표(`Tier Badge`, `소모 Cr`, `절감 Cr`, `LOC`) 항시 노출.
2. **실시간 프레즌스(Live Presence) 인디케이터**:
   - 🟢 `READY`: 선행 태스크 완료 대기 중 (준비 완료)
   - 🔵 `THINKING`: 사내 기억 및 컨텍스트 추론 중 (펄스 애니메이션)
   - 🟡 `CODING`: Git Worktree 격리 소스코드 작성 중 (`+LOC`)
   - 🟣 `TESTING`: 단위 테스트 실행 중
   - ⚪ `COMPLETED`: 작업 완수 및 Diff 패치 제출
   - 🔴 `BLOCKED`: 충돌 또는 사용자 개입 대기 중
3. **경량 관제실 피드 (Mission Control Activity Stream)**:
   - 복잡한 무거운 웹 IDE 에디터 없이, 시간 순서로 에이전트의 사고(Thought)와 액션(Action), 사용자 지시(User Chat)가 카카오톡/슬랙 스타일로 스크롤되는 미니 피드.
   - 하단 인풋 바를 통해 특정 에이전트에게 `@sub_1 ...` 지시 전달 지원.
4. **듀얼 인텐트(Dual-Intent) 스마트 입력 바 규격**:
   - **태스크 지시 (자연어 입력)**: 활성 태스크가 없거나 `@`로 시작하지 않는 일반 텍스트 입력 시, 2단계 서브태스크(구현, 검증)를 포함한 신규 TaskDAG를 자동 생성하여 `POST /v1/orchestrator/dispatch`로 즉시 백그라운드 발주.
   - **에이전트 힌트 주입 (`@sub_1 ...`)**: 특정 워커 지정 시 활성 DAG의 해당 워커 컨텍스트에 비차단 힌트 주입 (`POST /v1/orchestrator/tasks/{dag_id}/chat`).
   - **작업 중지 제어 (`중지`, `취소`, `/stop`, `/cancel`)**: 활성 DAG와 실행 중인 워커 프로세스를 즉시 안전하게 종료하고 상태를 `CANCELLED`로 전환 (`POST /v1/orchestrator/tasks/{dag_id}/cancel`).
   - **시스템 확인 응답(ACK)**: 사용자 입력 시 관제실 피드에 시스템 처리 상태(발주 완료, 힌트 수신, 중지 완료)를 즉시 피드백 카드로 표출.
   - **발신자/수신자 명확화 및 중복 방지 (`OPERATOR ➔ sub_1`)**: 사용자의 입력 지시는 발신자와 수신 대상 워커를 동시에 드러내는 `(OPERATOR ➔ {target_subtask})` 뱃지로 단 1회 렌더링되며, SSE 신호 재유입으로 인한 중복 버블 생성을 차단.
   - **실시간 상태 질의 인텐트 (Status Query Intent)**:
     - 사용자가 "상태 알려줘", "뭐하고 있어?", "진행 상황", "status", "ping" 등의 상태 질의 입력 시, 신규 작업을 발주하지 않고 관제실 피드에 에이전트 상태 요약 카드를 즉시 반환.
     - **활성 태스크 부재 시**: "현재 실행 중인 에이전트 작업이 없습니다 (유휴 상태). 작업을 발주하시려면 목표를 입력하세요." 안내 즉시 표출.
     - **활성 태스크 존재 시**: 특정 워커(`@sub_1 상태`) 또는 전체 워커의 프레즌스(`READY`/`CODING` 등), 수정 LOC, 소모 크레딧을 즉각 브리핑.
5. **상시 2-컬럼 뷰포트 보존 정책**:
   - 태스크가 0건일 때도 관제실 컬럼(`#missionControlCol`)을 절대 숨기지 않으며, 좌측 태스크 컬럼(`#tasksListCol`) 내부에 정갈한 Empty State 카드를 배치하여 사용자가 언제든 자연어로 즉시 작업을 발주할 수 있도록 보장.

---

## 6. 타겟 레포지토리 선택기(Repository Selector) 및 Codex CLI 하위 호환성 규격

### 6.1 기존 Codex CLI 동작 100% 보존 불변식 (Codex CLI Backward Compatibility Invariant)
1. **프록시 격리**: 기존 Codex CLI 및 IDE 플러그인이 호출하는 `/v1/responses`, `/v1/chat/completions` 엔드포인트는 타겟 레포 선택 기능과 완전히 분리되어 동작하며, 단 1바이트의 인터페이스 변경도 허용하지 않음.
2. **CLI CWD 우선 원칙**: 터미널에서 `harnex-task dispatch`를 실행할 때 별도 타겟 레포 인자가 없으면 기존과 동일하게 터미널 현재 실행 위치(`cwd="."`)를 100% 기본 베이스 레포로 사용.
3. **독립적 확장**: 웹 대시보드에서 선택된 타겟 레포는 대시보드 발주 태스크에만 스코프가 한정되며, 터미널 세션의 작업 위치를 강제 변경하지 않음.

### 6.2 대시보드 상단 타겟 레포 바 및 경량 디렉토리 트리 모달
1. **타겟 레포 헤더 바 (`#targetRepoBar`)**:
   - 멀티에이전트 탭 최상단에 현재 활성화된 대상 레포지토리 경로와 Git 브랜치 뱃지 표출:
     `[ 📂 대상 레포: /Users/HH191_1/workspace/travel-supporters ] 🌿 develop [변경]`
   - 기본값: Harnex 소스 디렉토리 또는 가장 최근 사용된 Git 레포지토리.
2. **경량 디렉토리 브라우저 API (`GET /v1/orchestrator/fs/browse`)**:
   - 쿼리 파라미터: `path` (선택, 기본: 현재 타겟 레포 또는 사용자 홈 디렉토리)
   - 응답 필드:
     - `current_path`: 현재 탐색 중인 절대 경로
     - `parent_path`: 상위 디렉토리 경로
     - `is_git_repo`: 현재 경로가 Git 저장소인지 여부 (`.git` 존재 여부)
     - `git_branch`: Git 저장소인 경우 현재 브랜치명
     - `directories`: 하위 디렉토리 목록 (폴더명, 절대 경로, Git 여부, 브랜치명)
     - `recent_repositories`: 최근 선택되었던 유효한 Git 저장소 목록 (최대 5개)
3. **타겟 레포 선택 모달 (`#repoSelectModal`)**:
   - 최근 작업 저장소 1-클릭 바로가기 버튼 제공.
   - 상위 디렉토리 이동(`..`) 및 하위 디렉토리 드릴다운 네비게이션.
   - 검색창을 통한 실시간 폴더 필터링.
   - Git 저장소(`🌿`)인 폴더만 활성화된 `[이 프로젝트 선택]` 버튼 노출 (비 Git 폴더는 진입만 가능하여 안전 보장).
4. **작업 발주 시 타겟 레포 바인딩**:
   - 대시보드 채팅창에서 자연어 목표 입력 후 [전송] 시, 현재 선택된 `target_repo` 경로가 `TaskDAG` 메타데이터에 자동 주입되어 `POST /v1/orchestrator/dispatch`로 전달됨.
   - 워커는 해당 타겟 레포에서 직접 독립된 Git Worktree를 생성하여 소스코드를 분석 및 수정.
