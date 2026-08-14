# 🚀 Deployment Architecture & Environment Configuration Reference

이 문서는 개발 저장소(Dev Workspace)와 실제 서비스 런타임(Production Live Runtime)을 완벽 격리하고, 환경변수 및 숨겨진 설정을 종합 관리하는 **배포 아키텍처 및 설정 명세서**입니다.

---

## 1. 배포 격리 아키텍처 (Deployment Isolation Architecture)

개발자의 로컬 저장소 위치가 어디든(`$PWD`), 실제 서비스 프록시는 사용자 개인 홈 디렉토리 하위의 독립 런타임 경로(`$HOME/.tierbridge/live`)에서 구동됩니다.

```text
[개발 저장소 (Dev Workspace)]                  [실제 서비스 런타임 (Production Live)]
/path/to/any/agent-cli                         ~/.tierbridge/live/
 ├─ 소스코드 편집 & 단위 테스트                  ├─ harness.py (Port 18080 가동)
 ├─ 브랜치 전환 & 자유로운 실험                   ├─ harness.log (독립 수집)
 └─ ./deploy.sh 실행 ─── (안전 동기화 & 핫패치) ─► └─ harness.pid (프로세스 관리)
```

---

## 2. 배포 및 구동 스크립트 스펙

1. **`deploy.sh` (원클릭 배포 스크립트)**:
   - 개발 레포의 소스를 `$HOME/.tierbridge/live`로 동기화.
   - 파이썬 가상환경 패키지 자동 체크 및 설치.
   - 기존 Port 18080 프록시 프로세스를 안전 종료 후 배포본에서 무중단/1초 재가동.
2. **`run_harness.sh` (환경변수 주입 및 프록시 시드 스크립트)**:
   - `source run_harness.sh` 실행 시 현재 터미널 세션에 필요한 모든 환경변수 자동 주입.
   - 런타임 프록시 미가동 시 배포 스크립트 자동 유도 및 서비스 가동.

---

## 3. 종합 환경변수 및 숨겨진 설정 목록 (Full Environment Variables Reference)

TierBridge 시스템 및 연동 모듈에서 사용하는 전체 환경변수 및 기본값 목록입니다:

| 환경변수 (Environment Variable) | 기본값 (Default) | 설명 (Description) |
| :--- | :--- | :--- |
| **`OPENAI_BASE_URL`** | `http://localhost:18080/v1` | Codex CLI 및 OpenAI/vLLM 호환 가로채기 URL |
| **`CODEX_API_BASE`** | `http://localhost:18080/v1` | Codex Enterprise 연동용 API 엔드포인트 BASE |
| **`LOCALAI_URL`** | `http://localhost:18080` | Codex `--local-provider=localai` 호스트 가로채기 |
| **`OLLAMA_HOST`** | `http://localhost:18080` | Codex 로컬 프로바이더 호스트 가로채기 |
| **`CODEX_OSS_PORT`** | `18080` | Codex 로컬 공급자 수신 포트 |
| **`ENTERPRISE_API_URL`** | `https://chatgpt.com/backend-api/codex/responses` | 업스트림 OpenAI Enterprise 백엔드 API 엔드포인트 |
| **`HARNESS_PORT`** | `18080` | 하네스 프록시가 바인딩하여 수신하는 로컬 포트 |
| **`AUTH_FILE_PATH`** | `~/.codex/auth.json` | 엔터프라이즈 JWT 인증 토큰 자동 파싱 경로 |
| **`SQLITE_VEC_PATH`** | `""` (자동 탐색) | `sub-memory-bootstrap` 벡터 확장 모듈 경로 |
| **`METRICS_LOG_PATH`** | `.sub-memory/metrics.jsonl` | 기억 회수 기여도 및 메트릭 수집 경로 |
| **`METRICS_RETENTION_DAYS`** | `30` | 메트릭 로그 보관 일수 |
