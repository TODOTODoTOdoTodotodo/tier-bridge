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

# Detect and terminate any existing process on 18080
PID=$(lsof -t -i:$PORT)
if [ ! -z "$PID" ]; then
    echo "⚠️  Port $PORT is currently occupied by PID: $PID. Cleaning up..."
    kill -9 $PID
    sleep 1
else
    echo "✅ Port $PORT is free and ready."
fi

echo "🚀 [Step 2/5] Starting LLM Routing Harness Proxy in background..."
if [ ! -f "harness.py" ]; then
    echo "❌ Error: harness.py not found in current directory!"
    exit 1
fi

# Run uvicorn in the background, logging to harness.log
$PYTHON_BIN -m uvicorn harness:app --host 0.0.0.0 --port $PORT --reload > "$HARNESS_LOG" 2>&1 &
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

echo "🚀 [Step 3/5] Running routing diagnostics and self-tests..."
if [ -f "test_client.py" ]; then
    echo "Running decision test cases..."
    $PYTHON_BIN test_client.py decision > /dev/null 2>&1
    sleep 2 # Wait for logs to flush to harness.log
    echo ""
    echo "📋 [Harness Routing Decisions Captured]:"
    grep "➔ \[DECISION\]" "$HARNESS_LOG" | tail -n 7
    echo ""
else
    echo "⚠️  Warning: test_client.py not found. Skipping self-test."
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
echo "💡 만약 'source run_harness.sh' 로 실행하셨다면,"
echo "   환경 변수 4개가 현재 터미널 세션에 자동으로 주입되었습니다!"
echo "   즉시 아래 명령어로 연동하여 첫 명령을 내리실 수 있습니다:"
echo ""
echo "  codex --oss --local-provider=ollama <원하는_명령>"
echo "  (예: codex --oss --local-provider=ollama chat)"
echo ""
echo "💡 (만약 그냥 ./run_harness.sh 로 실행하셨다면 아래를 수동으로 입력해 주세요)"
echo "  export OPENAI_BASE_URL=\"http://localhost:$PORT/v1\""
echo "  export CODEX_API_BASE=\"http://localhost:$PORT/v1\""
echo "  export OLLAMA_HOST=\"http://127.0.0.1:$PORT\""
echo "  export CODEX_OSS_PORT=$PORT"
echo "-------------------------------------------------------------"
