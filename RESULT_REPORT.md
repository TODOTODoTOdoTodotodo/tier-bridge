# 결과 보고서

## 작업 요약

- 로컬 프록시 기반 라우팅 하네스를 점검했습니다.
- 분류기 인증 문제와 fallback 경로를 수정했습니다.
- 중간 난이도 등급을 추가했습니다.
- decision 테스트를 별도로 분리해 라우팅만 확인할 수 있게 했습니다.

## 반영된 변경

- `LUNA:MEDIUM`과 `TERRA:MEDIUM` 분류 기준을 추가했습니다.
- 분류 프롬프트를 보수적으로 조정했습니다.
- `TERRA:*`는 모두 `gpt-5.6-terra`로 매핑했습니다.
- `LUNA:*`는 `gpt-5.6-luna`로 매핑했습니다.
- production fallback은 비용 친화적으로 유지했습니다.
- production과 mock 경로 모두 `reasoning`을 등급별로 반영하도록 정리했습니다.

## 검증 결과

- `MINI` 분류가 정상 동작했습니다.
- `LUNA:LOW` 분류가 정상 동작했습니다.
- `TERRA:EXTRA_HIGH` 분류가 정상 동작했습니다.
- `TERRA:MAX` 분류가 정상 동작했습니다.
- 추가 로그에서 `authorization_present=true`, `chatgpt_account_id_present=true`가 확인되었습니다.

## 특이사항

- production 경로에서도 `reasoning`을 전달합니다.
- 따라서 실제 엔터프라이즈 전달은 모델과 추론 수준을 함께 반영합니다.
- 분류기 호출은 `~/.codex/auth.json`의 실제 토큰을 자동 사용합니다.
- 테스트 초기에 더미 Authorization 헤더가 섞여 401이 발생했으나 제거했습니다.
- 중간 단계에서 `payload` 참조 순서 오류가 있었으나 수정 완료했습니다.

## 다음 확인 포인트

- `TERRA:MEDIUM`의 실제 기준이 너무 넓지 않은지 여부
- 필요 시 `LUNA:HIGH` 같은 추가 세분화 여부
