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
