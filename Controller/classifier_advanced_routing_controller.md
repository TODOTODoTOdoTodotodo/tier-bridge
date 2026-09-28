# Advanced SOLID Classifier & Multi-Stage Adaptive Routing Specification

## 1. 개요 및 목적 (Background & Objectives)
기존 TierBridge의 단일 LLM 의존적 분류기 구조를 탈피하여, **객체지향 SOLID 원칙(Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion)**에 입각한 5단계 하이브리드 파이프라인(Multi-Stage Pipeline) 아키텍처로 전면 고도화합니다.

코드 내 하드코딩이나 임의 판단 로직을 배제하고, 모든 임계값·가중치·패턴은 외재화된 설정 파일(`config/classifier_policy.json`)을 통해 런타임에 동적으로 주입 및 관리됩니다.

또한 대시보드 UI는 **HTML5 UP**(Dimension, Hyperspace, Editorial 계열)의 모던한 미니멀리즘 다크 글래스모피즘 디자인 언어를 계승하여, 고도화된 분류기 텔레메트리(Fast-Path 처리율, 예산 거버너 모드, 에스컬레이션 현황)를 세련되게 시각화합니다.

---

## 2. SOLID 설계 원칙 적용 구조

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Inbound Request Context                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             ClassifierPipeline (Orchestrator, DIP 준수)                │
│                                                                        │
│   [Stage 1: FastPathStage] (SRP: 정적/규칙 기반 초고속 0ms 패스)         │
│         │ (미매칭 시)                                                  │
│         ▼                                                              │
│   [Stage 2: ContextMetricsStage] (SRP: 토큰/파일 규모 물리적 복잡도)   │
│         │                                                              │
│         ▼                                                              │
│   [Stage 3: EscalationStage] (SRP: 린트/컴파일 에러 및 반복 턴 감지)   │
│         │                                                              │
│         ▼                                                              │
│   [Stage 4: BudgetGovernorStage] (SRP: 실시간 크레딧 잔여율 제어)      │
│         │                                                              │
│         ▼                                                              │
│   [Stage 5: DeepPathStage] (SRP: gpt-reserve / fallback LLM 심층 판정) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        ClassificationResult                            │
│  - tier: BRONZE | SILVER | GOLD | PLATINUM | DIAMOND | CHALLENGER      │
│  - stage_resolved: "fast_path" | "deep_path" | "escalated" | "budget"  │
│  - latency_ms, telemetry_metadata, cost_mode                          │
└────────────────────────────────────────────────────────────────────────┘
```

1. **SRP (Single Responsibility Principle)**:
   - 각 스테이지(`FastPath`, `ContextMetrics`, `Escalation`, `BudgetGovernor`, `DeepPath`)는 단 하나의 판정 기준만을 책임집니다.
2. **OCP (Open/Closed Principle)**:
   - 신규 판정 스테이지나 규칙 추가 시 기존 코드를 수정하지 않고 `IClassifierStage` 인터페이스를 구현하여 파이프라인에 주입합니다.
3. **LSP (Liskov Substitution Principle)**:
   - 모든 판정 스테이지는 `IClassifierStage` 규격을 준수하며, 파이프라인 내에서 상호 교체 가능합니다.
4. **ISP (Interface Segregation Principle)**:
   - 클라이언트는 불필요한 메서드에 의존하지 않으며, `evaluate(context: ClassificationContext) -> StageDecision` 단일 책임 계약을 따릅니다.
5. **DIP (Dependency Inversion Principle)**:
   - 라우터 및 파이프라인은 구체 클래스가 아닌 `IClassifierStage` 추상화와 `ClassifierPolicyManager`에 의존합니다.

---

## 3. 외재화 설정 규격 (`config/classifier_policy.json`)

모든 규칙, 정규식, 임계치는 하드코딩 없이 JSON 설정으로 관리됩니다:
```json
{
  "version": "1.0.0",
  "fast_path": {
    "enabled": true,
    "max_token_length": 150,
    "simple_patterns": [
      "^\\s*(git\\s+status|git\\s+log|ls|pwd|whoami|date)\\s*$",
      "^\\s*(안녕|하이|test|ping|어디까지|확인|조회|목록)\\s*$",
      "^\\s*(오타\\s*수정|단순\\s*조회|파일\\s*읽기)\\s*$"
    ],
    "default_tier": "BRONZE"
  },
  "context_metrics": {
    "enabled": true,
    "large_context_tokens": 32000,
    "large_context_min_tier": "GOLD",
    "multi_file_count_threshold": 3,
    "multi_file_min_tier": "PLATINUM"
  },
  "escalation": {
    "enabled": true,
    "error_keywords": [
      "error", "exception", "failed", "traceback", "syntaxerror",
      "fail", "오류", "실패", "컴파일 에러", "테스트 실패"
    ],
    "max_escalation_steps": 2
  },
  "budget_governor": {
    "enabled": true,
    "eco_threshold_percent": 20.0,
    "critical_threshold_percent": 5.0,
    "eco_tier_ceiling": "GOLD",
    "critical_tier_ceiling": "BRONZE"
  }
}
```

---

## 4. REST API & 텔레메트리 규격

1. **`GET /v1/classifier/telemetry`**:
   - 실시간 처리율, Fast-Path 히트율, 에스컬레이션 횟수, 현재 예산 모드 반환.
2. **`GET /v1/dashboard/stats`**:
   - 대시보드 오토싱크에 고도화된 분류기 텔레메트리 지표 통합 반환.

---

## 5. UI/UX 디자인 규격 (HTML5 UP 계열 디자인 언어)
- **비주얼 언어**: HTML5 UP(Fractal / Editorial / Hyperspace) 테마 스타일:
  - 섬세한 트래킹의 대문자 라벨 (`tracking-wider`, `uppercase`, `text-xs`)
  - 깊이감 있는 글래스 카드와 미세한 보더라인 (`border-white/10`, `backdrop-blur-xl`)
  - 분류기 텔레메트리 위젯 (Fast-Path 레이쇼, 예산 거버너 뱃지, 실시간 에스컬레이션 인디케이터)

---

## 6. 정밀 격리 및 비용 절감액 수집 규격 (Precision Isolation & Cost Savings)

### 6.1 `ContextMetricsStage` 현재 턴 정밀 격리 규격
1. **히스토리 스캔 방지**:
   - 세션 전체 대화 누적 텍스트(`unified_request.messages`)를 합산하여 파일 패턴을 검색하던 방식은 대화 후반부 모든 단순 턴을 `PLATINUM`으로 오염시키므로 금지함.
   - 반드시 **현재 턴의 평가 프롬프트(`ctx.target_eval_prompt`) 및 최근 유저 입력(`ctx.user_prompt`)**만을 대상으로 다중 파일(`>= 3개`) 참조 여부를 판별함.
2. **장기 기억(Giyeok) 주입 블록 정제**:
   - 프롬프트에 주입된 장기 기억 연관 지식(`[🧠 Giyeok 장기 기억저장소 연관 지식]`) 블록을 사전에 제거한 순수 사용자 작업 지시문만을 대상으로 파일 개수를 집계함.
3. **토큰 바닥 티어(Floor)의 합리적 적용**:
   - 토큰 규모(`large_context_tokens: 32000`) 초과 시 `GOLD` 바닥을 적용하되, 단순 조회의 경우 `PLATINUM`으로 무조건 폭주하지 않도록 격리함.

### 6.2 `EscalationStage` 에러 피드백 정밀 판별 규격
1. **단어 경계(`\b`) 및 맥락 판별**:
   - 단순 문자열 포함(`"fail" in text`) 방식을 배제하고 영문 에러 키워드는 단어 경계(`\b`)를 적용하여 정상 단어(failsafe, available 등) 오탐지를 방지함.
2. **장기 기억 과거 에러 제외**:
   - 장기 기억 주입 텍스트 내의 과거 문제/해결책 문구는 현재 턴의 실패 피드백이 아니므로 검사 대상에서 필터링함.
3. **안전 승격 단계 제한**:
   - 단일 턴 내에서 한 번에 2단계를 초과하여 최상위(`CHALLENGER`)로 직행하지 않도록 점진적 승격 원칙을 준수함 (`max_escalation_steps: 1`).

### 6.3 CLI 및 대시보드 다운스케일링 절감액 집계 규격 (`analyze_usage.py`)
1. **다운스케일링 순수 절감액 공식**:
   $$\text{Saved USD} = \sum_{\text{LUNA}} (\text{InTok} \times \$2.50/M + \text{OutTok} \times \$10.00/M) - \sum \text{LunaCost}$$
   $$\text{Saved Credits} = \frac{\text{Saved USD}}{\$0.20}$$
2. **CLI 터미널 요약 출력**:
   - 메인 보고서 상단 KPI에 `🛡️ 다운스케일링 누적 절감액: $X.XX USD (약 X.X Credits 아낌)` 항목을 필수로 표출함.
3. **`-m ALL` 월 필터 정상화**:
   - CLI 인자로 `-m ALL` 또는 대소문자 무관하게 `ALL`이 전달될 경우 필터를 건너뛰고 전체 데이터를 정상 집계함.

