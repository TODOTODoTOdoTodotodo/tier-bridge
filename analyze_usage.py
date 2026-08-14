#!/usr/bin/env python3
import sys
import os

# Auto-inject src directory into sys.path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import re
import argparse
import webbrowser
import json
from collections import defaultdict
from datetime import datetime

def parse_args():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_log = os.path.join(script_dir, "harness.log") if os.path.exists(os.path.join(script_dir, "harness.log")) else "harness.log"
    
    parser = argparse.ArgumentParser(description="TierBridge 로그 기반 Kibana풍 USAGE 및 힐링팩터 모델 관리 분석기")
    parser.add_argument("log_file", nargs="?", default=default_log, help=f"분석할 로그 파일 경로 (기본: {default_log})")
    parser.add_argument("--date", "-d", type=str, help="특정 날짜 필터 (형식: YYYY-MM-DD)")
    parser.add_argument("--month", "-m", type=str, help="특정 월 필터 (형식: YYYY-MM)")
    parser.add_argument("--session", "-s", type=str, help="특정 세션 ID 필터 (예: 5eb61a1e)")
    parser.add_argument("--html", "-w", action="store_true", help="Kibana 스타일 시각화 웹 대시보드(usage_dashboard.html) 생성 및 브라우저 열기")
    parser.add_argument("--no-open", action="store_true", help="HTML 대시보드 생성 후 브라우저 자동 오픈 금지")
    return parser.parse_args()

def generate_html_dashboard(all_raw_records, records, daily_stats, monthly_stats, session_stats, decision_stats, prompt_stats, total_cost, total_credits, total_tokens, total_loc, target_date=None, target_month=None, target_session=None, healing_history=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    html_filename = os.path.join(script_dir, "usage_dashboard.html")
    
    # Healing Engine 상태 가져오기 (Smart Import)
    try:
        try:
            from tierbridge.healing_engine import HealingEngine
        except ImportError:
            from src.tierbridge.healing_engine import HealingEngine
        healing_status = HealingEngine.get_healing_status()
    except Exception as e:
        healing_status = {
            "has_new_healing": False,
            "active_version_id": "v1.0.0",
            "active_version": "latest",
            "sample_template": {
                "version_id": "v1.1.0-sample-demo",
                "name": "Healing Sample Demo v1.1.0 (Demo Test Hot-patch)",
                "description": "힐링팩터 핫패치 및 롤백 기능 동작을 검증하기 위한 데모 샘플 스냅샷"
            },
            "comparison": [
                {"tier": "LUNA:LOW", "current_model": "gpt-5.6-luna", "current_in_price": 1.0, "current_out_price": 3.0, "healing_model": "gpt-5.6-luna", "healing_in_price": 0.6, "healing_out_price": 1.8, "savings_pct": 40.0},
                {"tier": "LUNA:MEDIUM", "current_model": "gpt-5.6-luna", "current_in_price": 1.0, "current_out_price": 3.0, "healing_model": "gpt-5.6-luna", "healing_in_price": 0.6, "healing_out_price": 1.8, "savings_pct": 40.0},
                {"tier": "TERRA:MEDIUM", "current_model": "gpt-5.6-terra", "current_in_price": 2.5, "current_out_price": 10.0, "healing_model": "gpt-5.6-terra", "healing_in_price": 2.0, "healing_out_price": 8.0, "savings_pct": 20.0},
                {"tier": "TERRA:HIGH", "current_model": "gpt-5.6-terra", "current_in_price": 2.5, "current_out_price": 10.0, "healing_model": "gpt-5.6-terra", "healing_in_price": 2.0, "healing_out_price": 8.0, "savings_pct": 20.0},
                {"tier": "SOL:EXTRA_HIGH", "current_model": "gpt-5.6-sol", "current_in_price": 5.0, "current_out_price": 20.0, "healing_model": "gpt-5.6-sol", "healing_in_price": 4.5, "healing_out_price": 18.0, "savings_pct": 10.0}
            ],
            "all_versions": [
                {"version_id": "v1.0.0", "name": "Standard Baseline v1.0.0", "updated_at": "2026-07-31T00:00:00", "is_active": True, "is_latest": True}
            ]
        }

    healing_status_json = json.dumps(healing_status)
    healing_history_json = json.dumps(list(reversed(healing_history)) if healing_history else [])

    # 동적 월 선택 드롭다운 옵션 구성 (전체 원본 레코드 기준)
    available_months = sorted(list(set(r["month"] for r in all_raw_records if r["month"] != "Unknown Month")), reverse=True)
    month_options_html = '<option value="ALL" ' + ('selected' if not target_month else '') + '>전체 기간 (All Months)</option>'
    for m in available_months:
        selected_attr = 'selected' if target_month == m else ''
        month_options_html += f'<option value="{m}" {selected_attr}>{m}</option>'

    # 동적 세션 선택 드롭다운 옵션 구성
    available_sessions = sorted(list(set(r["session_id"] for r in all_raw_records if r["session_id"] and r["session_id"] != "N/A")))
    session_options_html = '<option value="ALL" ' + ('selected' if not target_session else '') + '>전체 세션 (All Sessions)</option>'
    for s in available_sessions:
        s_short = s[:8] if len(s) > 8 else s
        selected_attr = 'selected' if target_session == s else ''
        session_options_html += f'<option value="{s}" {selected_attr}>{s} ({s_short})</option>'

    # 동적 모델 버전 선택 드롭다운 옵션 구성
    all_versions = healing_status.get("all_versions", [])
    version_options_html = ""
    for v in all_versions:
        vid = v.get("version_id")
        vname = v.get("name", "")
        is_act = v.get("is_active", False)
        selected_attr = "selected" if is_act else ""
        active_label = " (Active)" if is_act else ""
        version_options_html += f'<option value="{vid}" {selected_attr}>{vid} - {vname}{active_label}</option>'

    if not version_options_html:
        version_options_html = '<option value="v1.0.0" selected>v1.0.0 - Standard Baseline (Active)</option>'

    # Client-side JavaScript 처리를 위한 원본 JSON 데이터 구성
    client_records = []
    for r in all_raw_records:
        client_records.append({
            "date": r["date"],
            "month": r["month"],
            "session_id": r["session_id"],
            "decision": r["decision"],
            "model": r["model"],
            "prompt": r["prompt"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "total_tokens": r["total_tokens"],
            "loc": r["loc"],
            "cost": r["cost"]
        })
    client_records_json = json.dumps(client_records)
    
    has_healing_banner = healing_status.get("has_new_healing", False)
    banner_hidden_class = "" if has_healing_banner else "hidden"

    html_content = f"""<!DOCTYPE html>
<html lang="ko" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TierBridge Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body {{ font-family: 'Inter', sans-serif; background-color: #0b0f19; }}
        .glass-card {{ background: rgba(15, 23, 42, 0.75); backdrop-filter: blur(12px); border: 1px solid rgba(51, 65, 85, 0.5); }}
    </style>
</head>
<body class="text-slate-100 min-h-screen p-6 md:p-10">

    <!-- Header -->
    <header class="flex flex-col md:flex-row md:items-center md:justify-between mb-8 pb-6 border-b border-slate-800">
        <div>
            <div class="flex items-center gap-3 mb-1">
                <span class="p-2.5 bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 rounded-xl">
                    <i class="fa-solid fa-chart-line text-xl"></i>
                </span>
                <h1 class="text-2xl md:text-3xl font-bold bg-gradient-to-r from-sky-400 via-indigo-300 to-emerald-400 bg-clip-text text-transparent">
                    TierBridge Dashboard
                </h1>
            </div>
            <p class="text-slate-400 text-sm pl-12">
                Codex Enterprise AI 사용량, 토큰 소모 및 모델 관리 대시보드
            </p>
        </div>
        
        <!-- Controls: Dynamic Month & Session Selectors, Model Version Selector, Live Indicator & Sample Test Button -->
        <div class="mt-4 md:mt-0 flex flex-wrap items-center gap-3">
            <!-- Dynamic Month Dropdown Selector -->
            <div class="flex items-center gap-2 bg-slate-800/90 border border-indigo-500/40 px-3 py-1.5 rounded-xl shadow-lg">
                <i class="fa-solid fa-calendar-check text-indigo-400 text-sm"></i>
                <span class="text-xs font-semibold text-slate-300">월:</span>
                <select id="monthSelect" onchange="onFilterChange()" 
                        class="bg-slate-900 text-emerald-400 font-mono text-xs font-bold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-indigo-400 cursor-pointer">
                    {month_options_html}
                </select>
            </div>

            <!-- Dynamic Session ID Dropdown Selector -->
            <div class="flex items-center gap-2 bg-slate-800/90 border border-purple-500/40 px-3 py-1.5 rounded-xl shadow-lg">
                <i class="fa-solid fa-network-wired text-purple-400 text-sm"></i>
                <span class="text-xs font-semibold text-slate-300">세션:</span>
                <select id="sessionSelect" onchange="onFilterChange()" 
                        class="bg-slate-900 text-purple-300 font-mono text-xs font-bold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-purple-400 cursor-pointer max-w-[180px] truncate">
                    {session_options_html}
                </select>
            </div>

            <!-- Model Version Selector -->
            <div class="flex items-center gap-2 bg-slate-800/90 border border-sky-500/40 px-3 py-1.5 rounded-xl shadow-lg">
                <i class="fa-solid fa-code-branch text-sky-400 text-sm"></i>
                <span class="text-xs font-semibold text-slate-300">모델 버전:</span>
                <select id="versionSelect" onchange="switchModelVersion(this.value)"
                        class="bg-slate-900 text-sky-300 font-mono text-xs font-bold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-sky-400 cursor-pointer">
                    {version_options_html}
                </select>
            </div>

            <!-- 3s Live Sync Badge -->
            <div id="liveSyncBadge" class="flex items-center gap-2 bg-emerald-950/60 border border-emerald-500/40 px-3 py-1.5 rounded-xl shadow-lg text-emerald-400 text-xs font-bold animate-pulse">
                <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                <span>3s Live Auto-Sync</span>
            </div>

            <!-- Healing Factor Demo Sample Test Button -->
            <button onclick="openHealingModal()"
                    class="px-3.5 py-1.5 bg-gradient-to-r from-purple-600/30 to-indigo-600/30 border border-purple-400/50 text-purple-200 text-xs font-bold rounded-xl shadow-lg hover:bg-purple-600/40 transition-all flex items-center gap-2">
                <i class="fa-solid fa-vial-circle-check text-purple-300"></i>
                <span>🧪 힐링 핫패치 데모 샘플</span>
            </button>

            <!-- Healing Notice Button (Visible ONLY when REAL new model detected) -->
            <button id="healingNoticeBtn" onclick="openHealingModal()"
                    class="{banner_hidden_class} px-3.5 py-1.5 bg-gradient-to-r from-emerald-500/20 to-teal-500/20 border border-emerald-500/50 text-emerald-300 text-xs font-bold rounded-xl shadow-lg hover:bg-emerald-500/30 transition-all flex items-center gap-2">
                <i class="fa-solid fa-kit-medical text-emerald-400"></i>
                <span>💡 실제 신규 모델 감지됨!</span>
            </button>
        </div>
    </header>

    <!-- Healing Factor Banner -->
    <div id="healingBanner" class="{banner_hidden_class} mb-8 p-4 rounded-2xl glass-card border border-emerald-500/40 bg-gradient-to-r from-emerald-950/40 via-slate-900 to-slate-900 flex flex-col md:flex-row items-center justify-between gap-4">
        <div class="flex items-center gap-3">
            <span class="p-3 bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 rounded-xl text-xl">
                <i class="fa-solid fa-wand-magic-sparkles"></i>
            </span>
            <div>
                <h3 class="text-sm font-bold text-emerald-300 flex items-center gap-2">
                    Real Upstream Model Released! <span class="text-xs px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded-full font-mono">Cost Saver</span>
                </h3>
                <p class="text-xs text-slate-300 mt-0.5" id="healingBannerDesc">
                    실제 업스트림 API에서 신규 릴리즈 모델 및 단가 절약 패치가 감지되었습니다. 원클릭 핫패치를 적용하세요.
                </p>
            </div>
        </div>
        <div class="flex items-center gap-2">
            <button onclick="openHealingModal()" class="px-4 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-extrabold rounded-xl shadow-lg transition-all flex items-center gap-1.5">
                <i class="fa-solid fa-code-compare"></i> 단가 비교 및 핫패치 적용
            </button>
        </div>
    </div>

    <!-- KPI Metric Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-5 mb-8">
        <!-- Card 1: Total Credits -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Total Consumed Credits</div>
            <div class="text-3xl font-extrabold text-emerald-400 font-mono mb-1" id="kpiCredits">0.00 <span class="text-sm font-normal text-slate-400">Cr</span></div>
            <div class="text-xs font-mono" id="kpiCreditBreakdown"><span class="text-indigo-300 font-bold">🤖 모델: 0.00 Cr</span> <span class="text-slate-500">|</span> <span class="text-amber-300 font-bold">🔍 분류기: 0.00 Cr</span></div>
            <div class="absolute -right-3 -bottom-3 text-emerald-500/10 text-6xl"><i class="fa-solid fa-credit-card"></i></div>
        </div>

        <!-- Card 2: Total Cost -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Estimated Value</div>
            <div class="text-3xl font-extrabold text-indigo-300 font-mono mb-1" id="kpiCost">$0.0000</div>
            <div class="text-xs text-slate-400" id="kpiRequests">총 0회 성사 요청</div>
            <div class="absolute -right-3 -bottom-3 text-indigo-500/10 text-6xl"><i class="fa-solid fa-dollar-sign"></i></div>
        </div>

        <!-- Card 3: Total Tokens -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Total Tokens</div>
            <div class="text-3xl font-extrabold text-sky-400 font-mono mb-1" id="kpiTokens">0</div>
            <div class="text-xs text-slate-400" id="kpiInTokens">Input: 0</div>
            <div class="absolute -right-3 -bottom-3 text-sky-500/10 text-6xl"><i class="fa-solid fa-cubes"></i></div>
        </div>

        <!-- Card 4: Total Sessions -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Unique Sessions</div>
            <div class="text-3xl font-extrabold text-purple-400 font-mono mb-1" id="kpiSessions">0 <span class="text-sm font-normal text-slate-400">sessions</span></div>
            <div class="text-xs text-slate-400">식별된 대화 세션 ID 수</div>
            <div class="absolute -right-3 -bottom-3 text-purple-500/10 text-6xl"><i class="fa-solid fa-layer-group"></i></div>
        </div>

        <!-- Card 5: Savings -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden border-emerald-500/30 bg-emerald-950/20">
            <div class="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-2">LUNA Auto-scaling Savings</div>
            <div class="text-3xl font-extrabold text-emerald-300 font-mono mb-1" id="kpiSavingsUsd">$0.00</div>
            <div class="text-xs text-emerald-400/80" id="kpiSavingsCredits">약 0.0 Cr 크레딧 아낌</div>
            <div class="absolute -right-3 -bottom-3 text-emerald-400/10 text-6xl"><i class="fa-solid fa-shield-halved"></i></div>
        </div>
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
        <!-- Daily Trend Line Chart -->
        <div class="lg:col-span-2 glass-card p-6 rounded-2xl">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
                    <i class="fa-solid fa-chart-area text-sky-400"></i> 선택 기간 일자별 추이 (Daily Trend)
                </h2>
                <span class="text-xs text-slate-400">Kibana Live Timeline</span>
            </div>
            <div class="h-64">
                <canvas id="dailyTrendChart"></canvas>
            </div>
        </div>

        <!-- Decision Grade Doughnut Chart -->
        <div class="glass-card p-6 rounded-2xl">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
                    <i class="fa-solid fa-chart-pie text-purple-400"></i> 모델 라우팅 등급 분포 (Decision Share)
                </h2>
                <span class="text-xs text-slate-400">Credit Share</span>
            </div>
            <div class="h-64 flex items-center justify-center">
                <canvas id="decisionChart"></canvas>
            </div>
        </div>
    </div>

    <!-- Top Consuming Prompts Table -->
    <div class="glass-card p-6 rounded-2xl mb-8">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
            <div>
                <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                    <i class="fa-solid fa-fire text-amber-400"></i> Top 크레딧 소모 프롬프트 턴 & 세션 인사이트
                </h2>
                <p class="text-xs text-slate-400 mt-1" id="promptTableSubTitle">
                    기본 Top 15 표시 • 세션 검색 시 해당 세션 내 전용 랭킹 및 프롬프트 턴을 표시합니다.
                </p>
            </div>
            <div class="relative">
                <input type="text" id="searchInput" placeholder="프롬프트/풀 세션ID/축약ID 검색..." onkeyup="filterTable()" 
                       class="bg-slate-900/80 border border-slate-700 text-slate-200 text-xs rounded-xl px-4 py-2 pl-9 focus:outline-none focus:border-indigo-500 w-72">
                <i class="fa-solid fa-magnifying-glass absolute left-3 top-2.5 text-slate-500 text-xs"></i>
            </div>
        </div>

        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse" id="promptTable">
                <thead>
                    <tr class="bg-slate-800/80 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700">
                        <th class="px-4 py-3 rounded-tl-xl" id="rankColHeader">Rank</th>
                        <th class="px-4 py-3">Session ID</th>
                        <th class="px-4 py-3">Prompt Content / Step Context</th>
                        <th class="px-4 py-3 text-right">요청 횟수</th>
                        <th class="px-4 py-3 text-right">총 토큰</th>
                        <th class="px-4 py-3 text-right">소모 달러 ($)</th>
                        <th class="px-4 py-3 text-right">소모 크레딧</th>
                        <th class="px-4 py-3 text-center rounded-tr-xl">최종 라우팅 등급</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800" id="promptTableBody">
                    <!-- Dynamic JavaScript Table Insertion -->
                </tbody>
            </table>
        </div>

        <!-- Load More Button -->
        <div class="mt-4 pt-4 border-t border-slate-800/80 flex items-center justify-between">
            <span class="text-xs text-slate-400" id="promptDisplayCountInfo">표시 중: Top 15개 턴</span>
            <button id="loadMoreBtn" onclick="loadMorePrompts()"
                    class="px-4 py-2 bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/40 text-indigo-300 text-xs font-bold rounded-xl transition-all flex items-center gap-1.5">
                <i class="fa-solid fa-chevron-down text-xs"></i> 🔽 더보기 (15개 더 로드)
            </button>
        </div>
    </div>

    <!-- Recent Hot-Patch & Version History Card -->
    <div class="glass-card p-6 rounded-2xl mb-8">
        <div class="flex items-center justify-between mb-4">
            <div>
                <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
                    <i class="fa-solid fa-clock-rotate-left text-emerald-400"></i> 모델 핫패치 & 버전 전환 이력 (Hot-Patch & Version Audit History)
                </h2>
                <p class="text-xs text-slate-400 mt-1">
                    하네스 무중단 핫패칭 및 원클릭 버전 스위칭 이벤트 실시간 기록
                </p>
            </div>
            <span class="text-xs px-2.5 py-1 bg-emerald-500/20 text-emerald-300 font-mono rounded-lg border border-emerald-500/30">Live Audit Log</span>
        </div>
        <div class="overflow-x-auto">
            <table class="w-full text-left text-xs border-collapse">
                <thead>
                    <tr class="bg-slate-800/80 text-slate-400 uppercase border-b border-slate-700">
                        <th class="px-4 py-3">타임스탬프</th>
                        <th class="px-4 py-3">이벤트 유형</th>
                        <th class="px-4 py-3">상세 기록 / 적용 내역</th>
                    </tr>
                </thead>
                <tbody id="healingHistoryTableBody" class="divide-y divide-slate-800">
                    <!-- Populated dynamically via JS -->
                </tbody>
            </table>
        </div>
    </div>

    <!-- Healing Factor Comparison Modal -->
    <div id="healingModal" class="hidden fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass-card max-w-3xl w-full p-6 rounded-3xl border border-slate-700 shadow-2xl relative">
            <button onclick="closeHealingModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-200 text-lg">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <div class="flex items-center gap-3 mb-4">
                <span class="p-2.5 bg-emerald-500/20 text-emerald-400 rounded-xl text-lg">
                    <i class="fa-solid fa-scale-balanced"></i>
                </span>
                <div>
                    <h2 class="text-lg font-bold text-slate-100">Model Healing Factor: 비용 & 성능 비교표</h2>
                    <p class="text-xs text-slate-400">현재 활성 모델 매핑 단가 vs 힐링 추천 모델 단가 비교 (데모 테스트 / 실제 릴리즈)</p>
                </div>
            </div>

            <div class="overflow-x-auto mb-6">
                <table class="w-full text-left text-xs border-collapse">
                    <thead>
                        <tr class="bg-slate-800/80 text-slate-300 border-b border-slate-700">
                            <th class="p-3">Tier</th>
                            <th class="p-3">현재 매핑 모델</th>
                            <th class="p-3 text-right">현재 단가 (In/Out)</th>
                            <th class="p-3 font-bold text-emerald-400">추천 힐링 모델</th>
                            <th class="p-3 text-right font-bold text-emerald-400">추천 단가 (In/Out)</th>
                            <th class="p-3 text-right font-bold text-indigo-400">예상 단가 절감율</th>
                        </tr>
                    </thead>
                    <tbody id="healingModalTableBody" class="divide-y divide-slate-800">
                        <!-- Populated by JS -->
                    </tbody>
                </table>
            </div>

            <div class="flex items-center justify-between pt-4 border-t border-slate-800">
                <div class="text-xs text-slate-400">
                    <i class="fa-solid fa-info-circle text-sky-400 mr-1"></i> [Apply Healing]을 누르면 하네스가 무중단으로 신규 버전을 생성하고 핫패치합니다.
                </div>
                <div class="flex items-center gap-3">
                    <button onclick="closeHealingModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl transition-colors">
                        취소
                    </button>
                    <button onclick="applyHealingPatch()" class="px-5 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-extrabold rounded-xl shadow-lg transition-all flex items-center gap-1.5">
                        <i class="fa-solid fa-bolt"></i> 🩹 Apply Model Healing (핫패치)
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="text-center text-xs text-slate-500 py-4 border-t border-slate-800/60">
        TierBridge Analytics Core • Powered by LLM Routing Harness Proxy • Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </footer>

    <!-- Client-side Interactive Scripts -->
    <script>
        let allRecords = {client_records_json};
        let healingData = {healing_status_json};
        let healingHistoryData = {healing_history_json};
        let dailyChart = null;
        let decisionChart = null;
        let currentPromptLimit = 15; // 기본 노출 15개

        function renderHealingHistory(historyList) {{
            const tbody = document.getElementById('healingHistoryTableBody');
            if (!tbody) return;
            tbody.innerHTML = '';
            const list = historyList || healingHistoryData || [];
            if (list.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="3" class="text-center py-4 text-slate-500">아직 수집된 핫패치/버전 전환 이력이 없습니다.</td></tr>';
                return;
            }}
            list.forEach(item => {{
                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-800/40 transition-colors';
                let badge = item.event_type === 'HEALING'
                    ? '<span class="px-2 py-0.5 bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 rounded-md font-bold">🩹 핫패치 적용</span>'
                    : '<span class="px-2 py-0.5 bg-sky-500/20 text-sky-300 border border-sky-500/40 rounded-md font-bold">🔀 버전 전환</span>';
                tr.innerHTML = `
                    <td class="px-4 py-3 font-mono text-slate-400">${{item.timestamp || 'N/A'}}</td>
                    <td class="px-4 py-3">${{badge}}</td>
                    <td class="px-4 py-3 font-mono text-slate-200">${{item.details || ''}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        function updateMonthSelector() {{
            const select = document.getElementById('monthSelect');
            if (!select) return;
            const currentVal = select.value || 'ALL';
            
            const months = Array.from(new Set(allRecords.map(r => r.month).filter(m => m && m !== 'Unknown Month'))).sort().reverse();
            
            select.innerHTML = '<option value="ALL">전체 기간 (All Months)</option>';
            months.forEach(m => {{
                const opt = document.createElement('option');
                opt.value = m;
                opt.text = m;
                if (m === currentVal) opt.selected = true;
                select.appendChild(opt);
            }});
            if (currentVal === 'ALL') select.value = 'ALL';
        }}

        function updateSessionSelector() {{
            const select = document.getElementById('sessionSelect');
            if (!select) return;
            const currentVal = select.value || 'ALL';
            
            const sessions = Array.from(new Set(allRecords.map(r => r.session_id).filter(s => s && s !== 'N/A'))).sort();
            
            select.innerHTML = '<option value="ALL">전체 세션 (All Sessions)</option>';
            sessions.forEach(s => {{
                const opt = document.createElement('option');
                opt.value = s;
                const sShort = s.length > 8 ? s.substring(0, 8) : s;
                opt.text = `${{s}} (${{sShort}})`;
                if (s === currentVal) opt.selected = true;
                select.appendChild(opt);
            }});
            if (currentVal === 'ALL') select.value = 'ALL';
        }}

        function initVersionSelector() {{
            const select = document.getElementById('versionSelect');
            if (!select) return;
            const allVersions = healingData.all_versions || [];
            const activeVid = healingData.active_version_id;
            
            if (allVersions.length > 0) {{
                select.innerHTML = '';
                allVersions.forEach(v => {{
                    const opt = document.createElement('option');
                    opt.value = v.version_id;
                    let label = v.version_id + ' - ' + (v.name || '');
                    if (v.is_active) label += ' (Active)';
                    opt.text = label;
                    if (v.is_active || (activeVid && v.version_id === activeVid)) {{
                        opt.selected = true;
                    }}
                    select.appendChild(opt);
                }});
            }}

            if (healingData.has_new_healing) {{
                document.getElementById('healingNoticeBtn').classList.remove('hidden');
                document.getElementById('healingBanner').classList.remove('hidden');
            }} else {{
                document.getElementById('healingNoticeBtn').classList.add('hidden');
                document.getElementById('healingBanner').classList.add('hidden');
            }}
        }}

        function openHealingModal() {{
            const tbody = document.getElementById('healingModalTableBody');
            tbody.innerHTML = '';
            const comp = healingData.comparison || [];
            comp.forEach(item => {{
                let savingsText = '';
                let savingsClass = '';
                if (item.savings_pct > 0) {{
                    savingsText = `+${{item.savings_pct}}% (절감)`;
                    savingsClass = 'text-emerald-400 font-bold';
                }} else if (item.savings_pct < 0) {{
                    savingsText = `${{item.savings_pct}}% (인상)`;
                    savingsClass = 'text-rose-400 font-bold';
                }} else {{
                    savingsText = '0.0% (동일)';
                    savingsClass = 'text-slate-400 font-semibold';
                }}

                const tr = document.createElement('tr');
                tr.className = 'hover:bg-slate-800/50';
                tr.innerHTML = `
                    <td class="p-3 font-semibold text-slate-200">${{item.tier}}</td>
                    <td class="p-3 font-mono text-slate-400">${{item.current_model || 'N/A'}}</td>
                    <td class="p-3 text-right font-mono text-slate-400">$${{item.current_in_price}} / $${{item.current_out_price}}</td>
                    <td class="p-3 font-mono font-bold text-emerald-400">${{item.healing_model}}</td>
                    <td class="p-3 text-right font-mono font-bold text-emerald-400">$${{item.healing_in_price}} / $${{item.healing_out_price}}</td>
                    <td class="p-3 text-right font-mono ${{savingsClass}}">${{savingsText}}</td>
                `;
                tbody.appendChild(tr);
            }});
            document.getElementById('healingModal').classList.remove('hidden');
        }}

        function closeHealingModal() {{
            document.getElementById('healingModal').classList.add('hidden');
        }}

        async function applyHealingPatch() {{
            let res = null;
            try {{
                res = await fetch('http://127.0.0.1:18080/v1/models/heal', {{ method: 'POST' }});
            }} catch(e) {{
                try {{
                    res = await fetch('http://localhost:18080/v1/models/heal', {{ method: 'POST' }});
                }} catch(e2) {{}}
            }}
            if (res && res.ok) {{
                const data = await res.json();
                if (data.success) {{
                    alert('✅ ' + data.message);
                    closeHealingModal();
                    await fetchLiveDashboardStats();
                }} else {{
                    alert('❌ 핫패치 실패: ' + JSON.stringify(data));
                }}
            }} else {{
                alert('⚠️ 핫패치 요청 전송 완료');
                closeHealingModal();
                await fetchLiveDashboardStats();
            }}
        }}

        async function switchModelVersion(vid) {{
            let res = null;
            try {{
                res = await fetch('http://127.0.0.1:18080/v1/models/version/switch', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ version_id: vid }})
                }});
            }} catch(e) {{
                try {{
                    res = await fetch('http://localhost:18080/v1/models/version/switch', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ version_id: vid }})
                    }});
                }} catch(e2) {{}}
            }}
            if (res && res.ok) {{
                await fetchLiveDashboardStats();
            }} else {{
                await fetchLiveDashboardStats();
            }}
        }}

        function loadMorePrompts() {{
            currentPromptLimit += 15;
            const currentMonth = document.getElementById('monthSelect').value;
            const currentSession = document.getElementById('sessionSelect').value;
            renderDashboard(currentMonth, currentSession);
        }}

        function renderDashboard(targetMonth, targetSession) {{
            let filteredRecords = allRecords;

            if (targetMonth && targetMonth !== 'ALL') {{
                filteredRecords = filteredRecords.filter(r => r.month === targetMonth);
            }}

            if (targetSession && targetSession !== 'ALL') {{
                filteredRecords = filteredRecords.filter(r => r.session_id === targetSession || r.session_id.includes(targetSession));
            }}

            if (filteredRecords.length === 0) {{
                document.getElementById('kpiCredits').innerText = '0.00 Cr';
                document.getElementById('kpiCost').innerText = '$0.0000';
                document.getElementById('kpiRequests').innerText = '총 0회 성사 요청';
                document.getElementById('kpiTokens').innerText = '0';
                document.getElementById('kpiInTokens').innerText = 'Input: 0';
                document.getElementById('kpiSessions').innerHTML = '0 <span class="text-sm font-normal text-slate-400">sessions</span>';
                document.getElementById('kpiSavingsUsd').innerText = '$0.00';
                document.getElementById('kpiSavingsCredits').innerText = '약 0.0 Cr 크레딧 아낌';
                document.getElementById('promptTableBody').innerHTML = '<tr><td colspan="8" class="text-center py-6 text-slate-500">해당 조건에 맞는 데이터가 없습니다.</td></tr>';
                document.getElementById('loadMoreBtn').classList.add('hidden');
                document.getElementById('promptDisplayCountInfo').innerText = '표시 중: 0개';
                return;
            }}

            let mainCost = 0;
            let clfCost = 0;
            let lunaCount = 0;
            let lunaCost = 0;

            filteredRecords.forEach(r => {{
                if (r.decision === 'CLASSIFIER') {{
                    clfCost += r.cost;
                }} else {{
                    mainCost += r.cost;
                    if (r.decision.includes('LUNA')) {{
                        lunaCost += r.cost;
                        lunaCount += 1;
                    }}
                }}
            }});

            const totalCost = mainCost + clfCost;
            const totalCredits = totalCost / 0.20;
            const mainCredits = mainCost / 0.20;
            const clfCredits = clfCost / 0.20;

            const totalIn = filteredRecords.reduce((acc, r) => acc + r.input_tokens, 0);
            const totalOut = filteredRecords.reduce((acc, r) => acc + r.output_tokens, 0);
            const totalTok = totalIn + totalOut;

            const sessions = new Set(filteredRecords.map(r => r.session_id)).size;
            const savedUsd = Math.max(0, (lunaCount * 0.12) - lunaCost);
            const savedCredits = savedUsd / 0.20;

            document.getElementById('kpiCredits').innerHTML = totalCredits.toFixed(2) + ' <span class="text-sm font-normal text-slate-400">Cr</span>';
            document.getElementById('kpiCreditBreakdown').innerHTML = `<span class="text-indigo-300 font-bold">🤖 모델: ${{mainCredits.toFixed(2)}} Cr</span> <span class="text-slate-500">|</span> <span class="text-amber-300 font-bold">🔍 분류기: ${{clfCredits.toFixed(2)}} Cr</span>`;
            document.getElementById('kpiCost').innerText = '$' + totalCost.toFixed(4);
            document.getElementById('kpiRequests').innerText = '총 ' + filteredRecords.length.toLocaleString() + '회 성사 (모델: $' + mainCost.toFixed(4) + ' / 분류기: $' + clfCost.toFixed(4) + ')';
            document.getElementById('kpiTokens').innerText = totalTok.toLocaleString();
            document.getElementById('kpiInTokens').innerText = 'Input: ' + totalIn.toLocaleString();
            document.getElementById('kpiSessions').innerHTML = sessions.toLocaleString() + ' <span class="text-sm font-normal text-slate-400">sessions</span>';
            document.getElementById('kpiSavingsUsd').innerText = '$' + savedUsd.toFixed(2);
            document.getElementById('kpiSavingsCredits').innerText = '약 ' + savedCredits.toFixed(1) + ' Cr 크레딧 아낌';

            const dailyMap = {{}};
            filteredRecords.forEach(r => {{
                if (!dailyMap[r.date]) dailyMap[r.date] = {{ cost: 0, tokens: 0 }};
                dailyMap[r.date].cost += r.cost;
                dailyMap[r.date].tokens += r.total_tokens;
            }});

            const sortedDates = Object.keys(dailyMap).sort();
            const dailyCreditsData = sortedDates.map(d => (dailyMap[d].cost / 0.20).toFixed(2));
            const dailyTokensData = sortedDates.map(d => dailyMap[d].tokens);

            if (dailyChart) {{
                dailyChart.data.labels = sortedDates;
                dailyChart.data.datasets[0].data = dailyCreditsData;
                dailyChart.data.datasets[1].data = dailyTokensData;
                dailyChart.update();
            }} else {{
                dailyChart = new Chart(document.getElementById('dailyTrendChart'), {{
                    type: 'line',
                    data: {{
                        labels: sortedDates,
                        datasets: [
                            {{
                                label: 'Consumed Credits (Cr)',
                                data: dailyCreditsData,
                                borderColor: '#34d399',
                                backgroundColor: 'rgba(52, 211, 153, 0.1)',
                                borderWidth: 3,
                                fill: true,
                                tension: 0.35,
                                yAxisID: 'y'
                            }},
                            {{
                                label: 'Total Tokens',
                                data: dailyTokensData,
                                borderColor: '#38bdf8',
                                backgroundColor: 'rgba(56, 189, 248, 0.05)',
                                borderWidth: 2,
                                borderDash: [4, 4],
                                fill: false,
                                tension: 0.35,
                                yAxisID: 'y1'
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ labels: {{ color: '#94a3b8', font: {{ family: 'Inter' }} }} }}
                        }},
                        scales: {{
                            x: {{ grid: {{ color: 'rgba(51, 65, 85, 0.3)' }}, ticks: {{ color: '#94a3b8' }} }},
                            y: {{ position: 'left', grid: {{ color: 'rgba(51, 65, 85, 0.3)' }}, ticks: {{ color: '#34d399' }} }},
                            y1: {{ position: 'right', grid: {{ drawOnChartArea: false }}, ticks: {{ color: '#38bdf8' }} }}
                        }}
                    }}
                }});
            }}

            const decMap = {{}};
            filteredRecords.forEach(r => {{
                if (!decMap[r.decision]) decMap[r.decision] = 0;
                decMap[r.decision] += r.cost;
            }});

            const decLabels = Object.keys(decMap).sort((a,b) => decMap[b] - decMap[a]);
            const decCreditsData = decLabels.map(k => (decMap[k] / 0.20).toFixed(2));

            if (decisionChart) {{
                decisionChart.data.labels = decLabels;
                decisionChart.data.datasets[0].data = decCreditsData;
                decisionChart.update();
            }} else {{
                decisionChart = new Chart(document.getElementById('decisionChart'), {{
                    type: 'doughnut',
                    data: {{
                        labels: decLabels,
                        datasets: [{{
                            data: decCreditsData,
                            backgroundColor: ['#34d399', '#818cf8', '#fbbf24', '#f43f5e', '#a78bfa', '#38bdf8'],
                            borderWidth: 0
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {{
                            legend: {{ position: 'bottom', labels: {{ color: '#94a3b8', boxWidth: 12, font: {{ family: 'Inter', size: 11 }} }} }}
                        }}
                    }}
                }});
            }}

            // 프롬프트 그룹화 및 세션 랭킹 수합
            const promptMap = {{}};
            filteredRecords.forEach(r => {{
                const pKey = r.prompt ? r.prompt : "(서브 스텝 / 연속 릴레이)";
                if (!promptMap[pKey]) {{
                    promptMap[pKey] = {{
                        prompt: pKey,
                        count: 0,
                        tokens: 0,
                        cost: 0,
                        decision: r.decision,
                        session_id: r.session_id
                    }};
                }}
                promptMap[pKey].count += 1;
                promptMap[pKey].tokens += r.total_tokens;
                promptMap[pKey].cost += r.cost;
            }});

            const allSortedPrompts = Object.values(promptMap).sort((a,b) => b.cost - a.cost);
            const totalPromptsCount = allSortedPrompts.length;

            const visiblePrompts = allSortedPrompts.slice(0, currentPromptLimit);
            let tableHtml = '';
            
            visiblePrompts.forEach((p, idx) => {{
                const credits = (p.cost / 0.20).toFixed(2);
                const sidFull = p.session_id || 'N/A';
                const sidShort = (sidFull !== 'N/A' && sidFull.length > 8) ? sidFull.substring(0, 8) : sidFull;
                
                let badgeClass = 'bg-amber-900/30 text-amber-300 border-amber-600/40';
                if (p.decision.includes('SILVER') || p.decision.includes('LUNA:MEDIUM')) {{
                    badgeClass = 'bg-slate-700/40 text-slate-200 border-slate-400/40';
                }} else if (p.decision.includes('GOLD') || p.decision.includes('TERRA:MEDIUM')) {{
                    badgeClass = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                }} else if (p.decision.includes('PLATINUM') || p.decision.includes('TERRA:HIGH')) {{
                    badgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
                }} else if (p.decision.includes('DIAMOND')) {{
                    badgeClass = 'bg-blue-500/20 text-blue-300 border-blue-400/40';
                }} else if (p.decision.includes('CHALLENGER') || p.decision.includes('SOL')) {{
                    badgeClass = 'bg-rose-500/20 text-rose-300 border-rose-500/40 font-extrabold animate-pulse';
                }}

                const safePrompt = p.prompt.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

                tableHtml += `
                <tr class="hover:bg-slate-800/50 transition-colors border-b border-slate-800/80" data-session-id="${{sidFull}}" data-session-short="${{sidShort}}">
                    <td class="px-4 py-3 text-slate-400 font-mono text-sm font-bold">${{idx + 1}}</td>
                    <td class="px-4 py-3 font-mono text-xs text-sky-400" title="${{sidFull}}">${{sidShort}}</td>
                    <td class="px-4 py-3 text-slate-200 font-medium max-w-md truncate" title="${{safePrompt}}">${{safePrompt}}</td>
                    <td class="px-4 py-3 text-right text-slate-300">${{p.count.toLocaleString()}}회</td>
                    <td class="px-4 py-3 text-right text-sky-400 font-mono">${{p.tokens.toLocaleString()}}</td>
                    <td class="px-4 py-3 text-right text-indigo-300 font-mono font-semibold">$${{p.cost.toFixed(4)}}</td>
                    <td class="px-4 py-3 text-right text-emerald-400 font-mono font-bold">${{credits}} Cr</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2.5 py-1 text-xs font-semibold rounded-full border ${{badgeClass}}">
                            ${{p.decision}}
                        </span>
                    </td>
                </tr>
                `;
            }});

            document.getElementById('promptTableBody').innerHTML = tableHtml;

            // Load More 버튼 제어
            const loadMoreBtn = document.getElementById('loadMoreBtn');
            const countInfo = document.getElementById('promptDisplayCountInfo');

            if (currentPromptLimit >= totalPromptsCount) {{
                loadMoreBtn.classList.add('hidden');
                countInfo.innerText = `전체 ${{totalPromptsCount.toLocaleString()}}개 표시 완료`;
            }} else {{
                loadMoreBtn.classList.remove('hidden');
                countInfo.innerText = `표시 중: Top ${{visiblePrompts.length.toLocaleString()}} / 전체 ${{totalPromptsCount.toLocaleString()}}개`;
            }}

            // 필터링 적용 시 테이블 검색도 즉시 연동
            filterTable();
        }}

        function onFilterChange() {{
            currentPromptLimit = 15; // 필터 조작 시 15개 기본 초기화
            const targetMonth = document.getElementById('monthSelect').value;
            const targetSession = document.getElementById('sessionSelect').value;
            renderDashboard(targetMonth, targetSession);
        }}

        function filterTable() {{
            const input = document.getElementById('searchInput').value.toLowerCase().trim();
            const rows = document.querySelectorAll('#promptTable tbody tr');
            let visibleCount = 0;

            rows.forEach((row, idx) => {{
                const text = row.innerText.toLowerCase();
                const fullSid = (row.getAttribute('data-session-id') || '').toLowerCase();
                const shortSid = (row.getAttribute('data-session-short') || '').toLowerCase();

                const isMatch = !input || text.includes(input) || fullSid.includes(input) || shortSid.includes(input);
                row.style.display = isMatch ? '' : 'none';

                if (isMatch) {{
                    visibleCount++;
                    // 세션 ID 검색 시 세션 전용 랭크 (Session Rank 1, 2, 3...) 로 재계산
                    if (input.includes('sess_') || input.length >= 6) {{
                        row.querySelector('td').innerText = visibleCount;
                    }}
                }}
            }});
        }}

        // 3초 주기 실시간 라이브 자동 갱신 (Real-time Live Auto-Sync Polling)
        async function fetchLiveDashboardStats() {{
            let res = null;
            try {{
                res = await fetch('http://127.0.0.1:18080/v1/dashboard/stats');
            }} catch(e) {{
                try {{
                    res = await fetch('http://localhost:18080/v1/dashboard/stats');
                }} catch(e2) {{ }}
            }}

            const badge = document.getElementById('liveSyncBadge');
            if (res && res.ok) {{
                if (badge) {{
                    badge.className = "flex items-center gap-2 bg-emerald-950/60 border border-emerald-500/40 px-3 py-1.5 rounded-xl shadow-lg text-emerald-400 text-xs font-bold animate-pulse";
                    badge.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400"></span><span>3s Live Connected</span>';
                }}
                const data = await res.json();
                if (data.records && data.records.length > 0) {{
                    allRecords = data.records;
                    updateMonthSelector();
                    updateSessionSelector();
                }}
                if (data.healing_status) {{
                    healingData = data.healing_status;
                    initVersionSelector();
                }}
                if (data.healing_history) {{
                    healingHistoryData = data.healing_history;
                    renderHealingHistory(data.healing_history);
                }}
                const currentMonth = document.getElementById('monthSelect').value;
                const currentSession = document.getElementById('sessionSelect').value;
                renderDashboard(currentMonth, currentSession);
            }} else {{
                if (badge) {{
                    badge.className = "flex items-center gap-2 bg-rose-950/60 border border-rose-500/40 px-3 py-1.5 rounded-xl shadow-lg text-rose-400 text-xs font-bold";
                    badge.innerHTML = '<span class="w-2 h-2 rounded-full bg-rose-400"></span><span>Live Disconnected</span>';
                }}
            }}
        }}

        window.onload = function() {{
            initVersionSelector();
            renderHealingHistory(healingHistoryData);
            const initialMonth = document.getElementById('monthSelect').value;
            const initialSession = document.getElementById('sessionSelect').value;
            renderDashboard(initialMonth, initialSession);
            setInterval(fetchLiveDashboardStats, 3000);
        }};
    </script>
</body>
</html>
"""
    with open(html_filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ [Kibana Real-time Live Dashboard] 성공적으로 생성되었습니다: {os.path.abspath(html_filename)}")
    return html_filename

def analyze(log_filepath, target_date=None, target_month=None, target_session=None, generate_html=False, open_browser=True):
    if not os.path.exists(log_filepath):
        print(f"❌ Error: 로그 파일을 찾을 수 없습니다: {log_filepath}")
        sys.exit(1)

    usage_pattern = re.compile(
        r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[USAGE\] (?P<decision>[^\s]+) \((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| loc=(?P<loc>\d+) lines)? \| cost=\$(?P<cost>[\d\.]+) USD'
    )
    decision_pattern = re.compile(
        r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[DECISION[^\]]*\] (?P<decision>[^\s]+) \([^)]+\) \| "(?P<prompt>[^"]*)"'
    )

    healing_pattern = re.compile(
        r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?➔ \[(?P<event_type>HEALING|VERSION_SWITCH)\] (?P<details>.*)$'
    )

    all_raw_records = []
    records = []
    prompt_history = []
    healing_history = []
    
    with open(log_filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            # HEALING & VERSION_SWITCH 수집
            h_match = healing_pattern.search(line)
            if h_match:
                healing_history.append({
                    "timestamp": h_match.group("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event_type": h_match.group("event_type"),
                    "details": h_match.group("details")
                })
                continue
            
            # DECISION 매칭 수집
            d_match = decision_pattern.search(line)
            if d_match:
                prompt_history.append({
                    "timestamp": d_match.group("timestamp"),
                    "sid": d_match.group("sid") or "N/A",
                    "decision": d_match.group("decision"),
                    "prompt": d_match.group("prompt")
                })
                continue
                
            # USAGE 매칭 수집
            u_match = usage_pattern.search(line)
            if u_match:
                ts_str = u_match.group("timestamp")
                sid_str = u_match.group("sid") or "N/A"
                dt = None
                date_key = "Unknown Date"
                month_key = "Unknown Month"
                if ts_str:
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        date_key = dt.strftime("%Y-%m-%d")
                        month_key = dt.strftime("%Y-%m")
                    except ValueError:
                        pass
                
                decision = u_match.group("decision")
                model = u_match.group("model")
                in_tok = int(u_match.group("in_tok"))
                out_tok = int(u_match.group("out_tok"))
                loc_val = int(u_match.group("loc")) if u_match.group("loc") else 0
                cost = float(u_match.group("cost"))

                # 가장 최근의 DECISION 프롬프트 연동
                associated_prompt = ""
                if prompt_history:
                    associated_prompt = prompt_history[-1]["prompt"]
                    if sid_str == "N/A" and prompt_history[-1]["sid"] != "N/A":
                        sid_str = prompt_history[-1]["sid"]

                if sid_str == "N/A" and associated_prompt:
                    import hashlib
                    prompt_hash = hashlib.md5(associated_prompt.encode("utf-8")).hexdigest()[:8]
                    sid_str = f"sess_{prompt_hash}"
                elif sid_str == "N/A":
                    sid_str = "sess_legacy"

                item = {
                    "datetime": dt,
                    "date": date_key,
                    "month": month_key,
                    "session_id": sid_str,
                    "decision": decision,
                    "model": model,
                    "prompt": associated_prompt,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": in_tok + out_tok,
                    "loc": loc_val,
                    "cost": cost
                }

                all_raw_records.append(item)

                # 날짜/월/세션 필터링 적용 (CLI용)
                if target_date and date_key != target_date:
                    continue
                if target_month and month_key != target_month:
                    continue
                if target_session and target_session.lower() not in sid_str.lower():
                    continue

                records.append(item)

    if not records:
        filter_msg = []
        if target_month: filter_msg.append(f"월: {target_month}")
        if target_date: filter_msg.append(f"일자: {target_date}")
        if target_session: filter_msg.append(f"세션ID: {target_session}")
        desc = ", ".join(filter_msg) if filter_msg else ""
        print(f"⚠️  분석할 [USAGE] 로그 레코드가 없습니다. ({desc})")
        return

    # 요약 집계
    total_reqs = len(records)
    total_in = sum(r["input_tokens"] for r in records)
    total_out = sum(r["output_tokens"] for r in records)
    total_tokens = total_in + total_out
    total_loc = sum(r["loc"] for r in records)
    total_cost = sum(r["cost"] for r in records)
    total_credits = total_cost / 0.20

    decision_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0})
    daily_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0})
    monthly_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0})
    session_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0})
    prompt_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0, "prompt": "", "decision": "", "session_id": ""})

    for r in records:
        d = r["decision"]
        dt_key = r["date"]
        m_key = r["month"]
        s_key = r["session_id"]
        p_key = r["prompt"] if r["prompt"] else "(서브 스텝 / 연속 릴레이)"
        
        decision_stats[d]["count"] += 1
        decision_stats[d]["in_tok"] += r["input_tokens"]
        decision_stats[d]["out_tok"] += r["output_tokens"]
        decision_stats[d]["loc"] += r["loc"]
        decision_stats[d]["cost"] += r["cost"]

        daily_stats[dt_key]["count"] += 1
        daily_stats[dt_key]["in_tok"] += r["input_tokens"]
        daily_stats[dt_key]["out_tok"] += r["output_tokens"]
        daily_stats[dt_key]["loc"] += r["loc"]
        daily_stats[dt_key]["cost"] += r["cost"]

        monthly_stats[m_key]["count"] += 1
        monthly_stats[m_key]["in_tok"] += r["input_tokens"]
        monthly_stats[m_key]["out_tok"] += r["output_tokens"]
        monthly_stats[m_key]["loc"] += r["loc"]
        monthly_stats[m_key]["cost"] += r["cost"]

        session_stats[s_key]["count"] += 1
        session_stats[s_key]["in_tok"] += r["input_tokens"]
        session_stats[s_key]["out_tok"] += r["output_tokens"]
        session_stats[s_key]["loc"] += r["loc"]
        session_stats[s_key]["cost"] += r["cost"]

        prompt_stats[p_key]["cost"] += r["cost"]
        prompt_stats[p_key]["prompt"] = p_key
        prompt_stats[p_key]["decision"] = d
        prompt_stats[p_key]["session_id"] = s_key

    print("====================================================================================================")
    print("📊 [TierBridge Dashboard] AI 사용량, 크레딧 & 모델 관리 보고서")
    print("====================================================================================================")
    if target_month: print(f"🗓️  조회 대상 월: {target_month}")
    if target_date: print(f"🗓️  조회 대상 일자: {target_date}")
    if target_session: print(f"🔀 조회 대상 세션 ID: {target_session}")
    print(f"📁 대상 로그 파일: {log_filepath}")
    print(f"📈 총 성공 요청 수 (Requests) : {total_reqs:,} 회")
    print(f"📥 총 Input 토큰 수          : {total_in:,} tokens")
    print(f"📤 총 Output 토큰 수         : {total_out:,} tokens")
    print(f"🔢 전체 총 소모 토큰 수       : {total_tokens:,} tokens")
    print(f"💻 총 작성/생성 코드 (LOC)    : {total_loc:,} lines")
    print(f"💰 총 추정 소모 비용         : ${total_cost:.6f} USD")
    print(f"💳 총 추정 소모 크레딧       : {total_credits:.2f} Credits (1 Credit = $0.20 USD)")
    print("----------------------------------------------------------------------------------------------------")

    print("\n[1] 🎯 등급(Decision)별 소모 분포")
    print(f"{'Decision 등급':<18} | {'요청 수':<8} | {'Input 토큰':<12} | {'Output 토큰':<12} | {'코드 (LOC)':<10} | {'비용 (USD)':<12} | {'예상 크레딧 (Credits)':<20}")
    print("-" * 105)
    for dec, s in sorted(decision_stats.items(), key=lambda x: x[1]["cost"], reverse=True):
        credits = s['cost'] / 0.20
        print(f"{dec:<18} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[2] 🗓️  일자(Daily)별 소모 요약")
    print(f"{'날짜':<12} | {'요청 수':<8} | {'Input 토큰':<12} | {'Output 토큰':<12} | {'코드 (LOC)':<10} | {'비용 (USD)':<12} | {'예상 크레딧 (Credits)':<20}")
    print("-" * 95)
    for date_str, s in sorted(daily_stats.items()):
        credits = s['cost'] / 0.20
        print(f"{date_str:<12} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[3] 🗓️  월별(Monthly) 소모 요약")
    print(f"{'년-월':<12} | {'요청 수':<8} | {'Input 토큰':<12} | {'Output 토큰':<12} | {'코드 (LOC)':<10} | {'비용 (USD)':<12} | {'예상 크레딧 (Credits)':<20}")
    print("-" * 95)
    for month_str, s in sorted(monthly_stats.items()):
        credits = s['cost'] / 0.20
        print(f"{month_str:<12} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[4] 🔀 세션(Session ID)별 소모 요약 (Top 10)")
    print(f"{'Session ID':<38} | {'요청 수':<8} | {'소모 토큰':<12} | {'비용 (USD)':<12} | {'소모 크레딧 (Credits)'}")
    print("-" * 95)
    top_sessions = sorted(session_stats.items(), key=lambda x: x[1]["cost"], reverse=True)[:10]
    for sid, s in top_sessions:
        credits = s['cost'] / 0.20
        tok_total = s['in_tok'] + s['out_tok']
        print(f"{sid:<38} | {s['count']:<8,} | {tok_total:<12,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[5] 💡 Top 크레딧 소모 프롬프트 턴 인사이트 (Top Prompt Insights)")
    print(f"{'Rank':<4} | {'소모 크레딧':<12} | {'소모 토큰':<10} | {'등급':<14} | {'프롬프트 요약'}")
    print("-" * 95)
    top_p = sorted(prompt_stats.values(), key=lambda x: x["cost"], reverse=True)[:5]
    for idx, p in enumerate(top_p, 1):
        c_val = p["cost"] / 0.20
        t_val = p["in_tok"] + p["out_tok"]
        p_short = p["prompt"][:45] + "..." if len(p["prompt"]) > 45 else p["prompt"]
        print(f"{idx:<4} | {c_val:.2f} Credits   | {t_val:<10,} | {p['decision']:<14} | {p_short}")

    print("====================================================================================================\n")

    if generate_html:
        html_file = generate_html_dashboard(all_raw_records, records, daily_stats, monthly_stats, session_stats, decision_stats, prompt_stats, total_cost, total_credits, total_tokens, total_loc, target_date, target_month, target_session, healing_history=healing_history)
        if open_browser:
            webbrowser.open("file://" + os.path.abspath(html_file))

if __name__ == "__main__":
    args = parse_args()
    analyze(args.log_file, target_date=args.date, target_month=args.month, target_session=args.session, generate_html=args.html, open_browser=not args.no_open)
