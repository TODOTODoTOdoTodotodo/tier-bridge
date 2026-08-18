# 결과 보고서 (Gaming RPG Rank Tier 라우팅 및 하네스 프록시 최적화)

## 작업 요약

- 로컬 프록시 기반 라우팅 하네스를 **6단계 게이밍 RPG 랭크 티어(`BRONZE` ~ `CHALLENGER`)** 전략으로 최종 고도화했습니다.
- 분류기 라우터 모델을 **`gpt-5.6-luna` (reasoning effort: `low`)**로 가동하여 난이도 판정 정확도를 높이고 분류기 전용 크레딧을 분리 집계(`➔ [USAGE] CLASSIFIER`)하도록 구축했습니다.
- 표준 3-Tier 모드(`BRONZE` ~ `DIAMOND`)와 `--model super` 단축 인자를 통한 4-Tier Sol 모드(`BRONZE` ~ `CHALLENGER`)를 CLI 실행 시점 동적 분기로 완비했습니다.
- **Model Healing Factor System**을 탑재하여 신규 모델 릴리즈 감지, 원클릭 핫패칭(`v1.1.0-healing-hotpatch`) 및 원클릭 롤백 스위칭을 구현했습니다.
- Kibana 스타일 실시간 대시보드(`usage_dashboard.html`)에 3초 라이브 오토싱크, 월별/세션별 동적 필터링, 크레딧 세부 분리(분류기/메인/전체) 및 핫패치 타임라인을 제공합니다.

## 반영된 변경

- **분류기 라우터**: `gpt-5.6-luna` (`low` effort) 적용 및 `CLASSIFIER` 크레딧 별도 추적
- **최저 모델 하한선**: `BRONZE` (`gpt-5.6-luna`, `low` effort)
- **표준 모드 상한선**: `DIAMOND` (`gpt-5.6-terra`, `extra_high` effort)
- **4-Tier Sol 상한선**: `CHALLENGER` (`gpt-5.6-sol`, `extra_high` effort)
- **상세 등급 및 리즈닝 체계**:
  - `BRONZE`: `gpt-5.6-luna`, `low` (최저 기본 / 안전 폴백)
  - `SILVER`: `gpt-5.6-luna`, `medium` (표준 비즈니스 로직 / 단일 파일 리팩토링)
  - `GOLD`: `gpt-5.6-terra`, `medium` (중간 복잡도 / 복수 컴포넌트 연동)
  - `PLATINUM`: `gpt-5.6-terra`, `high` (복잡한 알고리즘 / 아키텍처 설계)
  - `DIAMOND`: `gpt-5.6-terra`, `extra_high` (교착상태 / 메모리 누수 / 딥 최적화 - 3-Tier Max)
  - `CHALLENGER`: `gpt-5.6-sol`, `extra_high` (커널/데드락 디버깅 - 4-Tier Max)
- **원스텝 가동 스크립트(`run_harness.sh`)**:
  - 기본 실행: 자가 진단 생략 (빠른 쾌속 가동)
  - 진단 포함 구동: `./run_harness.sh --test` 또는 `RUN_TESTS=true` 사용

## 검증 결과

- `./run_harness.sh --test` 수행 시 아래 라우팅 진단 케이스 전원 정상 통과:
  - `BRONZE` ("명령어 오타 수정 방안") ➔ `gpt-5.6-luna` (`low`)
  - `BRONZE` ("파이썬에서 단순 정렬 알고리즘 작성해줘") ➔ `gpt-5.6-luna` (`low`)
  - `SILVER` ("기존 입력 검증 로직을 리팩토링하고 중복을 줄여줘") ➔ `gpt-5.6-luna` (`medium`)
  - `GOLD` ("서비스 간 호출 흐름을 정리하고 중간 난이도 아키텍처 수정안을 제시해줘") ➔ `gpt-5.6-terra` (`medium`)
  - `PLATINUM` ("복잡한 알고리즘과 다중 컴포넌트 구조를 함께 설계해줘") ➔ `gpt-5.6-terra` (`high`)
  - `DIAMOND` ("사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘") ➔ `gpt-5.6-terra` (`extra_high`)

## 다음 확인 포인트

- 월 1,000 크레딧 한도 내 `BRONZE` / `SILVER` 저비용 랭크 소모 비중 실시간 추적 (`./analyze_usage.py --html` 대시보드 활용)
