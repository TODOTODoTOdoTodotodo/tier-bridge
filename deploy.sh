#!/usr/bin/env bash
set -e

# ==============================================================================
# TierBridge 원클릭 런타임 배포 스크립트 (Production Live Deployer)
# 개발 레포($PWD) ➔ 개인 라이브 런타임($HOME/.tierbridge/live) 동기화 및 무중단 재가동
# ==============================================================================

DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIVE_DIR="$HOME/.tierbridge/live"
PID_FILE="$HOME/.tierbridge/harness.pid"
PORT=18080

echo "🚀 [TierBridge Deployer] 배포 시작..."
echo "📂 개발 저장소 경로 : $DEV_DIR"
echo "🌐 라이브 런타임 경로: $LIVE_DIR"

# 1. 라이브 디렉토리 생성
mkdir -p "$LIVE_DIR"
mkdir -p "$HOME/.tierbridge"

# 2. 소스코드 동기화 & 로그 마이그레이션
echo "📦 소스코드 핫-동기화 진행 중..."
if command -v rsync >/dev/null 2>&1; then
    rsync -av \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='harness.log' \
        --exclude='usage_dashboard.html' \
        "$DEV_DIR/" "$LIVE_DIR/"
else
    cp -R "$DEV_DIR/"* "$LIVE_DIR/"
fi

# 개발 레포의 누적 harness.log 가 존재할 경우 라이브 harness.log 로 자동 병합 마이그레이션
if [ -f "$DEV_DIR/harness.log" ]; then
    python3 -c "
import os
dev_log = '$DEV_DIR/harness.log'
live_log = '$LIVE_DIR/harness.log'
if os.path.exists(dev_log):
    with open(dev_log, 'r', encoding='utf-8', errors='ignore') as f_dev:
        dev_lines = f_dev.readlines()
    live_content = open(live_log, 'r', encoding='utf-8', errors='ignore').read() if os.path.exists(live_log) else ''
    with open(live_log, 'a', encoding='utf-8') as f_out:
        for line in dev_lines:
            if line not in live_content:
                f_out.write(line)
" 2>/dev/null || true
fi

# 3. 라이브 가상환경(.venv) 및 의존성 패키지 정비
cd "$LIVE_DIR"
if [ ! -d ".venv" ]; then
    echo "🐍 라이브 파이썬 가상환경(.venv) 생성 중..."
    python3 -m venv .venv
fi

echo "📦 라이브 가상환경 패키지 및 tierbridge 모듈 설치 중..."
.venv/bin/python -m pip install -q fastapi uvicorn httpx python-dotenv 2>/dev/null || true
.venv/bin/python -m pip install -q -e . 2>/dev/null || true

# 4. 기존 가동 프록시 프로세스 안전 종료
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🛑 기존 하네스 프록시 (PID: $OLD_PID) 안전 종료 중..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
fi

# 18080 포트 점유 프로세스 강제 해제 (점유 남아있을 경우)
OCCUPIED_PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$OCCUPIED_PID" ]; then
    echo "🧹 Port $PORT 점유 프로세스(PID: $OCCUPIED_PID) 해제..."
    kill -9 $OCCUPIED_PID 2>/dev/null || true
    sleep 1
fi

# 5. 라이브 런타임에서 하네스 백그라운드 가동 (PYTHONPATH=src 설정 & --log-level warning 적용)
echo "⚡ 라이브 하네스 프록시 서버 가동 중 (Port: $PORT, LogLevel: WARNING)..."
PYTHONPATH="$LIVE_DIR/src:$PYTHONPATH" nohup .venv/bin/python -m uvicorn harness:app --host 0.0.0.0 --port $PORT --log-level warning > "$LIVE_DIR/harness.log" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 2

# 6. 배포 헬스체크 및 결과 검증
HEALTH_CHECK=$(curl -s http://localhost:$PORT/v1/models || true)
if echo "$HEALTH_CHECK" | grep -q "object"; then
    echo "✅ [배포 완료] 하네스 프록시가 정상 가동 중입니다! (PID: $NEW_PID)"
    echo "📄 런타임 로그 위치: $LIVE_DIR/harness.log"
else
    echo "⚠️ [배포 경고] 헬스체크 응답 대기 중입니다. 로그를 확인하세요: $LIVE_DIR/harness.log"
fi

# 7. Shell Alias (~/.zshrc, ~/.bashrc) 자동 등록 및 업데이트
setup_alias() {
    local shell_rc="$1"
    if [ -f "$shell_rc" ]; then
        if ! grep -q "alias tierbridge=" "$shell_rc"; then
            echo "" >> "$shell_rc"
            echo "# TierBridge Global Aliases" >> "$shell_rc"
            echo "alias tierbridge=\"source \$HOME/.tierbridge/live/run_harness.sh\"" >> "$shell_rc"
            echo "alias tierbridge-log=\"tail -f \$HOME/.tierbridge/live/harness.log\"" >> "$shell_rc"
            echo "alias tierbridge-dash=\"\$HOME/.tierbridge/live/.venv/bin/python \$HOME/.tierbridge/live/analyze_usage.py \$HOME/.tierbridge/live/harness.log --html\"" >> "$shell_rc"
            echo "🔗 Shell Alias 가 $shell_rc 에 자동 등록되었습니다."
        fi
    fi
}

setup_alias "$HOME/.zshrc"
setup_alias "$HOME/.bashrc"
echo "💡 어디서든 'tierbridge'로 세션 연결, 'tierbridge-log'로 로그 모니터링이 가능합니다!"
