#!/bin/bash

# =====================================================================
# Codex Enterprise Routing Harness: One-Step Setup & Run Script
# =====================================================================
# This script terminates port conflicts, starts the FastAPI harness, 
# runs routing diagnostics, patches Codex auth session, and launches 
# environment variables for Codex CLI connection.
# =====================================================================

PORT=18080
HARNESS_LOG="harness.log"
PYTHON_BIN="./.venv/bin/python"
PIP_BIN="./.venv/bin/pip"

if [ ! -d ".venv" ]; then
    echo "🔧 Creating local virtual environment..."
    python3 -m venv .venv
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ Error: Python interpreter not found at $PYTHON_BIN"
    exit 1
fi

echo "🔧 Ensuring Python dependencies are installed..."
if [ ! -x "$PIP_BIN" ]; then
    echo "❌ Error: pip not found at $PIP_BIN"
    exit 1
fi

$PIP_BIN install -q -r requirements.txt

echo "🚀 [Step 1/5] Checking for port conflicts on port $PORT..."

# Detect and terminate any existing processes on port (handles multiple uvicorn reload PIDs)
PIDS=$(lsof -t -i:$PORT)
if [ ! -z "$PIDS" ]; then
    echo "⚠️  Port $PORT is occupied by active processes. Cleaning up..."
    # 공백 및 줄바꿈 기준으로 정확히 토큰화하여 각각 종료
    for pid in $(echo "$PIDS"); do
        if [ ! -z "$pid" ]; then
            echo "   -> Terminating PID: $pid"
            kill -9 $pid >/dev/null 2>&1
        fi
    done
    sleep 1
else
    echo "✅ Port $PORT is free and ready."
fi

# Parse command line arguments for optional test execution
RUN_TESTS=${RUN_TESTS:-false}
for arg in "$@"; do
    if [ "$arg" = "--test" ] || [ "$arg" = "--run-tests" ]; then
        RUN_TESTS=true
    fi
done

echo "🚀 [Step 2/5] Starting LLM Routing Harness Proxy in background..."
if [ ! -f "harness.py" ]; then
    echo "❌ Error: harness.py not found in current directory!"
    exit 1
fi

# Run uvicorn in the background (Dual Router handles requests dynamically per CLI call)
PYTHONPATH=./src PYTHONUNBUFFERED=1 $PYTHON_BIN -m uvicorn harness:app --host 0.0.0.0 --port $PORT --no-access-log --reload > "$HARNESS_LOG" 2>&1 &
SERVER_PID=$!

echo "⏳ Waiting for harness server to become responsive..."
for i in {1..10}; do
    if curl -s http://localhost:$PORT/v1/models > /dev/null; then
        echo "✅ Harness Proxy is online (PID: $SERVER_PID)!"
        break
    fi
    if [ $i -eq 10 ]; then
        echo "❌ Error: Harness server failed to respond within 10 seconds. Check $HARNESS_LOG for details."
        exit 1
    fi
    sleep 1
done

echo "🚀 [Step 3/5] Checking routing diagnostics and self-tests option..."
if [ "$RUN_TESTS" = "true" ]; then
    if [ -f "test_client.py" ]; then
        echo "Running decision test cases..."
        $PYTHON_BIN test_client.py decision > /dev/null 2>&1
        sleep 2 # Wait for logs to flush to harness.log
        echo ""
        echo "📋 [Harness Routing Decisions Captured]:"
        grep "➔ \[DECISION" "$HARNESS_LOG" | tail -n 7
        echo ""
    else
        echo "⚠️  Warning: test_client.py not found. Skipping self-test."
    fi
else
    echo "⏩ Self-tests disabled by default. (Pass --test or RUN_TESTS=true to enable)"
fi

echo "🚀 [Step 4/5] Patching 로컬 auth.json to API Key redirection mode..."
if [ -f "patch_auth.py" ]; then
    $PYTHON_BIN patch_auth.py
else
    echo "⚠️  Warning: patch_auth.py not found. Skipping auth patching."
fi

# Explicitly export parameters so they bind to the parent session if 'source'd
export OPENAI_BASE_URL="http://localhost:$PORT/v1"
export CODEX_API_BASE="http://localhost:$PORT/v1"
export OLLAMA_HOST="http://127.0.0.1:$PORT"
export CODEX_OSS_PORT=$PORT

echo "🚀 [Step 5/5] One-Step integration complete! 🎉"
echo "-------------------------------------------------------------"
echo "💡 Codex CLI 실행 시점에 원하는 라우터를 선택하여 명령을 전달할 수 있습니다:"
echo ""
echo "  1) 기존 3-Tier 라우터 (gpt-5.6-terra 캡핑 비용절감 모드):"
echo "     codex --oss --local-provider=ollama <명령>"
echo ""
echo "  2) 4-Tier Sol 라우터 (gpt-5.6-sol 까지 동적 확장 모드):"
echo "     codex --oss --local-provider=ollama --model super <명령>"
echo "     (또는 --model gpt-5.6-sol)"
echo "-------------------------------------------------------------"

if [ -t 0 ]; then
    echo ""
    printf "❓ 실시간 프록시 로그(tail -f %s)를 지금 바로 확인하시겠습니까? [Y/n]: " "$HARNESS_LOG"
    read -r REPLY
    case "$REPLY" in
        [Nn]* )
            echo "⏩ 로그 모니터링을 건너끕니다."
            ;;
        * )
            echo "📜 실시간 프록시 로그 모니터링을 시작합니다. (종료 시 Ctrl+C)"
            echo "-------------------------------------------------------------"
            tail -f "$HARNESS_LOG"
            ;;
    esac
fi
