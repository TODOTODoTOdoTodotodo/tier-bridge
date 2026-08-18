# 📑 Step 4: 하네스 ✕ sub-memory 통합 크레딧 절감 대시보드 리포팅 (Dashboard Synergy Analytics)

이 문서는 TierBridge 하네스의 사용량 로그(`harness.log`)와 `sub-memory-bootstrap` (Giyeok)의 메트릭 로그(`.sub-memory/metrics.jsonl`)를 결합 분석하여, 장기 기억 회수 덕분에 절감된 실제 크레딧(Cr) 수치를 Kibana 대시보드에 시각화하는 **Step 4 구현 작업지시서**입니다.

---

## 1. 작업 개요 및 목적 (Objectives)

- **목적**: `sub-memory-bootstrap`과의 시너지 효과를 정량적으로 시각화하여 "장기 기억 회수를 통해 복잡한 질문이 저비용 `BRONZE` / `SILVER` 라우팅으로 다운스케일되어 실제 아낀 크레딧(Cr)" 수치를 실시간 리포팅.
- **통합 분석 지표 (Synergy Metrics)**:
  1. **Memory Recall Hits**: 세션별 연관 기억 회수 누적 횟수
  2. **Memory-driven Cost Savings**: 기억 주입으로 난이도가 강하되어 아낀 크레딧 (Cr) 및 USD ($)

---

## 2. 연동 아키텍처 및 데이터 결합

```
[harness.log]                    [.sub-memory/metrics.jsonl]
 ├─ timestamp, session_id         ├─ timestamp, session_id
 ├─ decision (BRONZE/GOLD/etc)    ├─ recall_size, memory_contribution
 └─ cost_usd                      └─ mcp_tool_name
       │                                 │
       └──────────────┬──────────────────┘
                      ▼ [Join by session_id]
        [analyze_usage.py Parsing]
                      │
                      ▼
   [usage_dashboard.html - Synergy KPI Card]
```

---

## 3. 세부 구현 스펙 (Implementation Specs)

### 3.1 `analyze_usage.py` 메트릭 파서 확장
```python
def parse_sub_memory_metrics(metrics_filepath=".sub-memory/metrics.jsonl"):
    """
    sub-memory-bootstrap의 메트릭 로그 파싱
    """
    session_recall_map = defaultdict(lambda: {"recall_count": 0, "contribution_score": 0.0})
    if not os.path.exists(metrics_filepath):
        return session_recall_map

    with open(metrics_filepath, "r", encoding="utf-8") as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                sid = data.get("session_id") or data.get("tags", [None])[0]
                if sid:
                    session_recall_map[sid]["recall_count"] += 1
                    session_recall_map[sid]["contribution_score"] += data.get("memory_contribution", 1.0)
            except Exception:
                pass

    return session_recall_map
```

### 3.2 `usage_dashboard.html` KPI 카드 및 표 확장
* KPI Metrics 영역에 **Memory Recall Savings Card** 신설:
  - `Memory Recall Hits`: 총 기억 회수 횟수
  - `Memory-assisted Savings`: 약 0.0 Cr (기억 보조를 통해 절감된 크레딧)
* 프롬프트 테이블(`promptTable`)에 **Giyeok Memory Tag Badge (`🧠 Memory Recalled`)** 표시.

---

## 4. 검증 및 테스트 절차 (Verification Steps)

1. **로그 파싱 테스트**:
   * `./analyze_usage.py --html --no-open` 실행 시 `.sub-memory/metrics.jsonl`이 없거나 존재하는 환경 모두 오류 없이 통과하는지 검증.
2. **Kibana 대시보드 시각화 검증**:
   * `usage_dashboard.html`에서 Memory Recall KPI 카드 및 🧠 Memory Recalled 배지가 깨끗하게 표출되는지 브라우저에서 확인.

---

## 5. 차기 대화 세션 연계 안내
새로운 대화 세션에서 **"integration_step4_analytics.md 문서를 바탕으로 Step 4 하네스 ✕ sub-memory 통합 크레딧 절감 대시보드 리포팅 구현을 시작해줘"**라고 요청하시면 본 지시서대로 즉시 작업을 진행할 수 있습니다.
