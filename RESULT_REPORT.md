# 결과 보고서 (default-luna 라우팅 최적화)

## 작업 요약

- 로컬 프록시 기반 라우팅 하네스를 `default-luna` 전략으로 최종 보정했습니다.
- 분류기 라우터 모델을 `gpt-5.4-mini`에서 **`gpt-5.6-luna` (reasoning effort: `low`)**로 교체하여 난이도 판정 정확도를 높였습니다.
- 최저 기본 실행 모델 및 폴백 모델을 **`gpt-5.6-luna` (`low`)**로 지정하여 `gpt-5.4-mini` 모델의 호출을 전면 배제했습니다.
- 상한 추론 레벨을 **`gpt-5.6-terra` (`extra_high` / `xhigh`)**로 캡(Capping) 적용하여 `max` 추론으로 인한 기습적인 크레딧 과소모를 원천 차단했습니다.
- `run_harness.sh` 실행 시 자가 진단 테스트를 **기본 OFF**로 전환하고, `--test` 옵션을 통한 선택적 릴레이 스위치를 추가했습니다.

## 반영된 변경

- **분류기 라우터**: `gpt-5.6-luna` (`low` effort) 적용
- **최저 모델 하한선**: `gpt-5.6-luna` (`low` effort)
- **최대 모델 상한선**: `gpt-5.6-terra` (`extra_high` effort)
- **상세 등급 및 리즈닝 체계**:
  - `LUNA:LOW`: `gpt-5.6-luna`, `low` (최저 기본 / 안전 폴백)
  - `LUNA:MEDIUM`: `gpt-5.6-luna`, `medium` (표준 비즈니스 로직 / 단일 파일 리팩토링)
  - `TERRA:MEDIUM`: `gpt-5.6-terra`, `medium` (중간 복잡도 / 복수 컴포넌트 연동)
  - `TERRA:HIGH`: `gpt-5.6-terra`, `high` (복잡한 알고리즘 / 아키텍처 설계)
  - `TERRA:EXTRA_HIGH`: `gpt-5.6-terra`, `extra_high` (교착상태 / 메모리 누수 / 딥 최적화)
- **원스텝 가동 스크립트(`run_harness.sh`)**:
  - 기본 실행: 자가 진단 생략 (빠른 쾌속 가동)
  - 진단 포함 구동: `./run_harness.sh --test` 또는 `RUN_TESTS=true` 사용

## 검증 결과

- `./run_harness.sh --test` 수행 시 아래 6단계 라우팅 진단 케이스 전원 정상 통과:
  - `LUNA:LOW` ("명령어 오타 수정 방안") ➔ `gpt-5.6-luna` (`low`)
  - `LUNA:LOW` ("파이썬에서 단순 정렬 알고리즘 작성해줘") ➔ `gpt-5.6-luna` (`low`)
  - `LUNA:MEDIUM` ("기존 입력 검증 로직을 리팩토링하고 중복을 줄여줘") ➔ `gpt-5.6-luna` (`medium`)
  - `TERRA:MEDIUM` ("서비스 간 호출 흐름을 정리하고 중간 난이도 아키텍처 수정안을 제시해줘") ➔ `gpt-5.6-terra` (`medium`)
  - `TERRA:HIGH` ("복잡한 알고리즘과 다중 컴포넌트 구조를 함께 설계해줘") ➔ `gpt-5.6-terra` (`high`)
  - `TERRA:EXTRA_HIGH` ("사내 데이터 파이프라인의 메모리 누수 탐지 및 튜닝 최적화 방안 제시해줘") ➔ `gpt-5.6-terra` (`extra_high`)

## 다음 확인 포인트

- 월 1000 크레딧 한도 내 `LUNA` 대 `TERRA` 모델 소모 비중 실시간 추적 (`http://localhost:18080/usage` 활용)
