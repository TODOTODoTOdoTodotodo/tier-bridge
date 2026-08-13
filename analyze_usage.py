#!/usr/bin/env python3
import sys
import os
import re
import argparse
import webbrowser
import json
from collections import defaultdict
from datetime import datetime

def parse_args():
    parser = argparse.ArgumentParser(description="TierBridge 로그 기반 Kibana풍 USAGE 및 월별/세션별 통계 분석기")
    parser.add_argument("log_file", nargs="?", default="harness.log", help="분석할 로그 파일 경로 (기본: harness.log)")
    parser.add_argument("--date", "-d", type=str, help="특정 날짜 필터 (형식: YYYY-MM-DD)")
    parser.add_argument("--month", "-m", type=str, help="특정 월 필터 (형식: YYYY-MM)")
    parser.add_argument("--session", "-s", type=str, help="특정 세션 ID 필터 (예: 5eb61a1e)")
    parser.add_argument("--html", "-w", action="store_true", help="Kibana 스타일 시각화 웹 대시보드(usage_dashboard.html) 생성 및 브라우저 열기")
    parser.add_argument("--no-open", action="store_true", help="HTML 대시보드 생성 후 브라우저 자동 오픈 금지")
    return parser.parse_args()

def generate_html_dashboard(records, daily_stats, monthly_stats, session_stats, decision_stats, prompt_stats, total_cost, total_credits, total_tokens, total_loc, target_date=None, target_month=None, target_session=None):
    html_filename = "usage_dashboard.html"
    
    # 일자별 차트 데이터 구성
    sorted_dates = sorted(daily_stats.keys())
    chart_dates_json = json.dumps(sorted_dates)
    chart_credits_json = json.dumps([round(daily_stats[d]["cost"] / 0.20, 2) for d in sorted_dates])
    chart_tokens_json = json.dumps([daily_stats[d]["in_tok"] + daily_stats[d]["out_tok"] for d in sorted_dates])
    
    # 등급별 차트 데이터 구성
    sorted_decisions = sorted(decision_stats.keys(), key=lambda k: decision_stats[k]["cost"], reverse=True)
    chart_dec_labels_json = json.dumps(sorted_decisions)
    chart_dec_credits_json = json.dumps([round(decision_stats[d]["cost"] / 0.20, 2) for d in sorted_decisions])
    
    # 프롬프트 인사이트 데이터 TOP 15 구성
    top_prompts = sorted(prompt_stats.values(), key=lambda x: x["cost"], reverse=True)[:15]
    
    prompt_rows_html = ""
    for idx, p in enumerate(top_prompts, 1):
        prompt_txt = p["prompt"] if p["prompt"] else "(서브 스텝 / 연속 릴레이 스텝)"
        credits = round(p["cost"] / 0.20, 3)
        sid_txt = p.get("session_id", "N/A")
        sid_short = sid_txt[:8] if sid_txt != "N/A" else "N/A"
        
        badge_class = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
        if "TERRA" in p["decision"] or "SOL" in p["decision"]:
            badge_class = "bg-amber-500/20 text-amber-300 border-amber-500/30" if "MEDIUM" in p["decision"] else "bg-rose-500/20 text-rose-300 border-rose-500/30"
        
        prompt_rows_html += f"""
        <tr class="hover:bg-slate-800/50 transition-colors border-b border-slate-800/80">
            <td class="px-4 py-3 text-slate-400 font-mono text-sm">{idx}</td>
            <td class="px-4 py-3 font-mono text-xs text-sky-400" title="{sid_txt}">{sid_short}</td>
            <td class="px-4 py-3 text-slate-200 font-medium max-w-md truncate" title="{prompt_txt}">{prompt_txt}</td>
            <td class="px-4 py-3 text-right text-slate-300">{p['count']:,}회</td>
            <td class="px-4 py-3 text-right text-sky-400 font-mono">{p['in_tok'] + p['out_tok']:,}</td>
            <td class="px-4 py-3 text-right text-indigo-300 font-mono font-semibold">${p['cost']:.4f}</td>
            <td class="px-4 py-3 text-right text-emerald-400 font-mono font-bold">{credits:.2f} Cr</td>
            <td class="px-4 py-3 text-center">
                <span class="px-2.5 py-1 text-xs font-semibold rounded-full border {badge_class}">
                    {p['decision']}
                </span>
            </td>
        </tr>
        """

    # 절감액 추정 (Terra 대신 Luna로 처리되어 절약된 비율 계산)
    luna_cost = sum(decision_stats[d]["cost"] for d in decision_stats if "LUNA" in d)
    luna_count = sum(decision_stats[d]["count"] for d in decision_stats if "LUNA" in d)
    saved_usd = (luna_count * 0.12) - luna_cost if luna_count else 0.0
    saved_usd = max(0.0, saved_usd)
    saved_credits = saved_usd / 0.20

    filter_info = []
    if target_month: filter_info.append(f"월: {target_month}")
    if target_date: filter_info.append(f"일자: {target_date}")
    if target_session: filter_info.append(f"세션ID: {target_session}")
    filter_desc = ", ".join(filter_info) if filter_info else "전체 누적 통계"

    html_content = f"""<!DOCTYPE html>
<html lang="ko" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TierBridge Kibana AI Usage Analytics Dashboard</title>
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
                    TierBridge AI Kibana Analytics
                </h1>
            </div>
            <p class="text-slate-400 text-sm pl-12">
                Codex Enterprise 토큰 소모량, 차감 크레딧, 월별/세션별 & 프롬프트 인사이트 시각화 대시보드
            </p>
        </div>
        <div class="mt-4 md:mt-0 flex items-center gap-3">
            <span class="px-3.5 py-1.5 bg-slate-800/80 border border-slate-700 text-slate-300 text-xs font-mono rounded-lg">
                <i class="fa-regular fa-calendar mr-1.5 text-indigo-400"></i>
                {filter_desc}
            </span>
            <span class="px-3.5 py-1.5 bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold rounded-lg flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> Live Log Parser Active
            </span>
        </div>
    </header>

    <!-- KPI Metric Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-5 mb-8">
        <!-- Card 1: Total Credits -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Total Consumed Credits</div>
            <div class="text-3xl font-extrabold text-emerald-400 font-mono mb-1">{total_credits:.2f} <span class="text-sm font-normal text-slate-400">Cr</span></div>
            <div class="text-xs text-slate-400">1 Credit = $0.20 USD 기준</div>
            <div class="absolute -right-3 -bottom-3 text-emerald-500/10 text-6xl"><i class="fa-solid fa-credit-card"></i></div>
        </div>

        <!-- Card 2: Total Cost -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Estimated Value</div>
            <div class="text-3xl font-extrabold text-indigo-300 font-mono mb-1">${total_cost:.4f}</div>
            <div class="text-xs text-slate-400">총 {len(records):,}회 성사 요청</div>
            <div class="absolute -right-3 -bottom-3 text-indigo-500/10 text-6xl"><i class="fa-solid fa-dollar-sign"></i></div>
        </div>

        <!-- Card 3: Total Tokens -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Total Tokens</div>
            <div class="text-3xl font-extrabold text-sky-400 font-mono mb-1">{total_tokens:,}</div>
            <div class="text-xs text-slate-400">Input: {(sum(r['input_tokens'] for r in records)):,}</div>
            <div class="absolute -right-3 -bottom-3 text-sky-500/10 text-6xl"><i class="fa-solid fa-cubes"></i></div>
        </div>

        <!-- Card 4: Total Sessions -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden">
            <div class="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">Unique Sessions</div>
            <div class="text-3xl font-extrabold text-purple-400 font-mono mb-1">{len(session_stats):,} <span class="text-sm font-normal text-slate-400">sessions</span></div>
            <div class="text-xs text-slate-400">식별된 대화 세션 ID 수</div>
            <div class="absolute -right-3 -bottom-3 text-purple-500/10 text-6xl"><i class="fa-solid fa-layer-group"></i></div>
        </div>

        <!-- Card 5: Savings -->
        <div class="glass-card p-5 rounded-2xl relative overflow-hidden border-emerald-500/30 bg-emerald-950/20">
            <div class="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-2">LUNA Auto-scaling Savings</div>
            <div class="text-3xl font-extrabold text-emerald-300 font-mono mb-1">${saved_usd:.2f}</div>
            <div class="text-xs text-emerald-400/80">약 {saved_credits:.1f} Credits 크레딧 아낌</div>
            <div class="absolute -right-3 -bottom-3 text-emerald-400/10 text-6xl"><i class="fa-solid fa-shield-halved"></i></div>
        </div>
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
        <!-- Daily Trend Line Chart -->
        <div class="lg:col-span-2 glass-card p-6 rounded-2xl">
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-base font-semibold text-slate-200 flex items-center gap-2">
                    <i class="fa-solid fa-chart-area text-sky-400"></i> 일자별 크레딧 & 토큰 소모 추이 (Daily Trend)
                </h2>
                <span class="text-xs text-slate-400">Kibana Timeline</span>
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
                    <i class="fa-solid fa-fire text-amber-400"></i> Top 크레딧 소모 프롬프트 턴 & 인사이트 (Prompt Insights)
                </h2>
                <p class="text-xs text-slate-400 mt-1">가장 많은 크레딧과 토큰을 소모한 턴별 프롬프트 및 라우팅 등급 인사이트</p>
            </div>
            <div class="relative">
                <input type="text" id="searchInput" placeholder="프롬프트/세션ID 검색..." onkeyup="filterTable()" 
                       class="bg-slate-900/80 border border-slate-700 text-slate-200 text-xs rounded-xl px-4 py-2 pl-9 focus:outline-none focus:border-indigo-500 w-64">
                <i class="fa-solid fa-magnifying-glass absolute left-3 top-2.5 text-slate-500 text-xs"></i>
            </div>
        </div>

        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse" id="promptTable">
                <thead>
                    <tr class="bg-slate-800/80 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700">
                        <th class="px-4 py-3 rounded-tl-xl">Rank</th>
                        <th class="px-4 py-3">Session ID</th>
                        <th class="px-4 py-3">Prompt Content / Step Context</th>
                        <th class="px-4 py-3 text-right">요청 횟수</th>
                        <th class="px-4 py-3 text-right">총 토큰</th>
                        <th class="px-4 py-3 text-right">소모 달러 ($)</th>
                        <th class="px-4 py-3 text-right">소모 크레딧</th>
                        <th class="px-4 py-3 text-center rounded-tr-xl">최종 라우팅 등급</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-slate-800">
                    {prompt_rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Footer -->
    <footer class="text-center text-xs text-slate-500 py-4 border-t border-slate-800/60">
        TierBridge Analytics Core • Powered by LLM Routing Harness Proxy • Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </footer>

    <!-- Chart.js Scripts -->
    <script>
        const dailyDates = {chart_dates_json};
        const dailyCredits = {chart_credits_json};
        const dailyTokens = {chart_tokens_json};

        const decLabels = {chart_dec_labels_json};
        const decCredits = {chart_dec_credits_json};

        // Line Chart: Daily Trend
        new Chart(document.getElementById('dailyTrendChart'), {{
            type: 'line',
            data: {{
                labels: dailyDates,
                datasets: [
                    {{
                        label: 'Consumed Credits (Cr)',
                        data: dailyCredits,
                        borderColor: '#34d399',
                        backgroundColor: 'rgba(52, 211, 153, 0.1)',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.35,
                        yAxisID: 'y'
                    }},
                    {{
                        label: 'Total Tokens',
                        data: dailyTokens,
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

        // Doughnut Chart: Decision Share
        new Chart(document.getElementById('decisionChart'), {{
            type: 'doughnut',
            data: {{
                labels: decLabels,
                datasets: [{{
                    data: decCredits,
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

        // Table Filter Function
        function filterTable() {{
            const input = document.getElementById('searchInput').value.toLowerCase();
            const rows = document.querySelectorAll('#promptTable tbody tr');
            rows.forEach(row => {{
                const text = row.innerText.toLowerCase();
                row.style.display = text.includes(input) ? '' : 'none';
            }});
        }}
    </script>
</body>
</html>
"""
    with open(html_filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"✅ [Kibana Visual Dashboard] 성공적으로 생성되었습니다: {os.path.abspath(html_filename)}")
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

    records = []
    prompt_history = []
    
    with open(log_filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            
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
                
                # 날짜/월/세션 필터링 적용
                if target_date and date_key != target_date:
                    continue
                if target_month and month_key != target_month:
                    continue
                if target_session and target_session.lower() not in sid_str.lower():
                    continue

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

                records.append({
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
                })

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

        prompt_stats[p_key]["count"] += 1
        prompt_stats[p_key]["in_tok"] += r["input_tokens"]
        prompt_stats[p_key]["out_tok"] += r["output_tokens"]
        prompt_stats[p_key]["cost"] += r["cost"]
        prompt_stats[p_key]["prompt"] = p_key
        prompt_stats[p_key]["decision"] = d
        prompt_stats[p_key]["session_id"] = s_key

    print("\n====================================================================================================")
    print("📊 [TierBridge Kibana AI 사용량, 크레딧, 월별/세션별 인사이트 보고서]")
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
        html_file = generate_html_dashboard(records, daily_stats, monthly_stats, session_stats, decision_stats, prompt_stats, total_cost, total_credits, total_tokens, total_loc, target_date, target_month, target_session)
        if open_browser:
            webbrowser.open("file://" + os.path.abspath(html_file))

if __name__ == "__main__":
    args = parse_args()
    analyze(args.log_file, target_date=args.date, target_month=args.month, target_session=args.session, generate_html=args.html, open_browser=not args.no_open)
