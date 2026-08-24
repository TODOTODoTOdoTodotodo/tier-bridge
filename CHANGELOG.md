# 📝 TierBridge Changelog

- **[Step 1: Ingestion Pipeline]**: LLM 최종 해결책(`solution_text`)과 세션 로그를 비동기로 수집하는 지식 적재 파이프라인 구축 (`MemoryIngestionWorker`)
- **[Unified Storage Policy]**: 기억저장소 DB를 `~/.tierbridge/memory.db`로 일원화하고 기존 37건의 Giyeok 지식 자동 무손실 마이그레이션 지원 (`deploy.sh`)
- **[Dual Table & Session ID]**: Giyeok `nodes` 및 `memories` 테이블 듀얼 지원과 실제 `session_id` 메타데이터 결합 보존 및 파싱 개선 (`MemoryHandler`)
- **[Quality Noise Gating]**: `[Substep]` 단순 중간 보고 턴 적재를 차단하고 최초 질의·코드 수정(LOC>0)·고난도 에피소드만 선별 적재하도록 게이트 강화
- **[Step 2: Pre-fetch Recall]**: 50ms Strict Timeout Sandbox 내에서 과거 유사 문제 해결책을 회수하여 프롬프트에 선행 주입하는 모듈 구현 (`MemoryPrefetcher`)
- **[Real-time Recall & Store Log]**: 기억 적재(`➔ [MEMORY:STORED]`) 및 회수 결과(`➔ [MEMORY:RECALLED]` / `[MEMORY:RECALL_NONE]`) 실시간 하네스 로그 표준화
- **[LOC Accuracy Enhancement]**: 모든 언어 태그 및 줄바꿈을 지원하는 코드 블록 정규식 개선과 논스트림 모드 및 2중 안전망을 통한 LOC 집계 정확도 강화
- **[Dashboard Memory Tab]**: 실시간 관제 대시보드에 37건의 축적 지식 열람과 연관 기억 검색이 가능한 장기 기억저장소 탭 추가 (`analyze_usage.py`)
