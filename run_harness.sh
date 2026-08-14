#!/usr/bin/env bash

# ==============================================================================
# TierBridge Client Environment Seeder & Production Runtime Launcher
# 사용법: source run_harness.sh
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_DIR="$HOME/.tierbridge/live"
PORT=18080

# 1. 런타임 하네스 가동 여부 점검 (미가동 시 자동 배포)
if ! curl -s http://localhost:$PORT/v1/models >/dev/null 2>&1; then
    echo "⚙️ [TierBridge] 라이브 하네스 프록시가 가동되어 있지 않습니다. 배포 스크립트를 실행합니다..."
    if [ -f "$SCRIPT_DIR/deploy.sh" ]; then
        bash "$SCRIPT_DIR/deploy.sh"
    elif [ -f "$LIVE_DIR/deploy.sh" ]; then
        bash "$LIVE_DIR/deploy.sh"
    fi
fi

# 2. CLI 프록시 가로채기 환경변수 주입 (Full Multi-Provider Environment Variables)
export OPENAI_BASE_URL="http://localhost:18080/v1"
export CODEX_API_BASE="http://localhost:18080/v1"
export OLLAMA_HOST="http://localhost:18080"
export LOCALAI_URL="http://localhost:18080"
export CODEX_OSS_PORT="18080"
export HARNESS_PORT="18080"

echo "✅ [TierBridge Agent Ready] 하네스 프록시 세션 환경변수가 설정되었습니다:"
echo "   • OPENAI_BASE_URL = $OPENAI_BASE_URL"
echo "   • CODEX_API_BASE  = $CODEX_API_BASE"
echo "   • OLLAMA_HOST     = $OLLAMA_HOST"
echo "   • LOCALAI_URL     = $LOCALAI_URL"
