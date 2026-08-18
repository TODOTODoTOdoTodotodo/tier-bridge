# 📊 LOC (Lines of Code) 파싱 및 수집 설계서

이 문서는 TierBridge 하네스 프록시에서 LLM 모델이 생성 및 수정한 소스코드 줄 수(LOC)를 실시간 스트림 파싱을 통해 추출하고 수집하는 기능의 설계 문서입니다.

---

## 1. 개요 및 목적

OpenAI 및 ChatGPT Enterprise 백엔드 API 응답 메타데이터에는 토큰 소모량(`input_tokens`, `output_tokens`)만 존재하며, 코드 작성 라인 수(LOC) 메타데이터는 포함되어 있지 않습니다.

본 기능은 프록시가 응답 스트림 버퍼(`accumulated_buffer`)를 트래킹하여, 모델이 출력한 마크다운 코드 블록(` ``` ... ``` `) 내부의 실제 코드 줄 수를 실시간 파싱하고 `UsageTracker` 및 `harness.log`, `analyze_usage.py` 분석기에 정량적 지표로 집계하는 것을 목적으로 합니다.

---

## 2. 파싱 및 수집 메커니즘

1. **텍스트 스트림 복원**:
   * 비동기 스트리밍 연결이 종료된 후 수집된 바이너리 버퍼(`accumulated_buffer`)에서 전체 응답 텍스트(답변 본문)를 추출합니다.

2. **코드 블록 추출 (Code Block Extraction)**:
   * 마크다운 펜스 코드 블록 정규 표현식 사용:
     ```regex
     ```[\w\-]*\n(.*?)```
     ```
   * 코드 블록 내부의 줄 수(Line Count)를 카운트합니다.
   * 비어있는 빈 줄이나 펜스 시작/끝 라인을 제외한 실제 소스코드 줄 수를 합산합니다.

3. **`UsageTracker` 수집 및 로그 기록**:
   * 계산된 `loc` (Lines of Code) 수치를 `UsageTracker.track_request`에 전달합니다.
   * `harness.log` 출력 예시:
     ```text
     [2026-07-27 11:08:25] ➔ [USAGE] BRONZE (gpt-5.6-luna) | input=21 output=365 tokens | loc=42 lines | cost=$0.001116 USD
     ```
   * `/usage` API 응답 및 `analyze_usage.py` 리포트에 총 LOC 및 평균 LOC 표기.

---

## 3. 리포트 및 통계 연동

`analyze_usage.py` 실행 시:
* **총 작성 코드 라인 수 (Total Code LOC)**
* **요청당 평균 작성 코드 라인 수 (Avg LOC / Request)**
* **Gaming RPG Rank Tier별 LOC 분포** (`BRONZE`, `SILVER`, `GOLD`, `PLATINUM`, `DIAMOND`, `CHALLENGER`에서 작성된 소스코드 라인 수)
* **Kibana 실시간 대시보드 (`usage_dashboard.html`) LOC KPI 카드 및 도넛 차트 연동**
