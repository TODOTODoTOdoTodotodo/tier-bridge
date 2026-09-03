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
    parser.add_argument("--balance", "-b", action="store_true", help="ChatGPT Enterprise 백엔드 실시간 계정 잔여 크레딧 및 지출 한도 조회")
    parser.add_argument("--date", "-d", type=str, help="특정 날짜 필터 (형식: YYYY-MM-DD)")
    parser.add_argument("--month", "-m", type=str, help="특정 월 필터 (형식: YYYY-MM)")
    parser.add_argument("--session", "-s", type=str, help="특정 세션 ID 필터 (예: 5eb61a1e)")
    parser.add_argument("--html", "-w", action="store_true", help="Kibana 스타일 시각화 웹 대시보드(usage_dashboard.html) 생성 및 브라우저 열기")
    parser.add_argument("--no-open", action="store_true", help="HTML 대시보드 생성 후 브라우저 자동 오픈 금지")
    return parser.parse_args()

def show_enterprise_balance():
    import urllib.request
    auth_path = os.path.expanduser("~/.codex/auth.json")
    if not os.path.exists(auth_path):
        print(f"❌ [오류] 인증 설정 파일({auth_path})을 찾을 수 없습니다.")
        return
    try:
        with open(auth_path, "r", encoding="utf-8") as f:
            auth = json.load(f)
        tokens = auth.get("tokens", {})
        access_token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        
        req = urllib.request.Request("https://chatgpt.com/backend-api/codex/usage")
        req.add_header("Authorization", f"Bearer {access_token}")
        if account_id:
            req.add_header("chatgpt-account-id", account_id)
        req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            
        email = data.get("email", "N/A")
        plan = data.get("plan_type", "business")
        spend = data.get("spend_control", {}).get("individual_limit", {})
        limit = float(spend.get("limit", 0))
        used = float(spend.get("used", 0))
        remaining = float(spend.get("remaining", 0))
        used_pct = (used / limit * 100.0) if limit > 0 else 0.0
        rem_pct = max(0.0, 100.0 - used_pct) if limit > 0 else 100.0
        reset_at = spend.get("reset_at")
        reset_str = datetime.fromtimestamp(reset_at).strftime("%Y-%m-%d %H:%M:%S") if reset_at else "N/A"
        
        print("\n" + "=" * 85)
        print("💳 [ChatGPT Enterprise] 실시간 계정 잔여 크레딧 및 지출 한도 조회")
        print("=" * 85)
        print(f"👤 사용자 계정      : {email} (Plan: {plan})")
        print(f"🏢 계정 ID         : {account_id}")
        print("-" * 85)
        print("📊 크레딧 한도 및 소모 현황 (Monthly Spend Control):")
        print(f"  • 월간 할당 한도 (Limit)     : {limit:,.2f} Credits")
        print(f"  • 실제 누적 소모량 (Used)    : {used:,.2f} Credits ({used_pct:.1f}%)")
        print(f"  • 실제 잔여 크레딧 (Remaining): {remaining:,.2f} Credits ({rem_pct:.1f}%)")
        print(f"  • 크레딧 리셋 일시 (Reset)   : {reset_str}")
        print("=" * 85 + "\n")
    except Exception as e:
        print(f"\n❌ [오류] 엔터프라이즈 실시간 크레딧 조회 실패: {e}\n")

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
                {"tier": "BRONZE", "current_model": "gpt-5.6-luna", "current_in_price": 1.0, "current_out_price": 3.0, "healing_model": "gpt-5.6-luna", "healing_in_price": 0.6, "healing_out_price": 1.8, "savings_pct": 40.0},
                {"tier": "SILVER", "current_model": "gpt-5.6-luna", "current_in_price": 1.0, "current_out_price": 3.0, "healing_model": "gpt-5.6-luna", "healing_in_price": 0.6, "healing_out_price": 1.8, "savings_pct": 40.0},
                {"tier": "GOLD", "current_model": "gpt-5.6-terra", "current_in_price": 2.5, "current_out_price": 10.0, "healing_model": "gpt-5.6-terra", "healing_in_price": 2.0, "healing_out_price": 8.0, "savings_pct": 20.0},
                {"tier": "PLATINUM", "current_model": "gpt-5.6-terra", "current_in_price": 2.5, "current_out_price": 10.0, "healing_model": "gpt-5.6-terra", "healing_in_price": 2.0, "healing_out_price": 8.0, "savings_pct": 20.0},
                {"tier": "DIAMOND", "current_model": "gpt-5.6-terra", "current_in_price": 2.5, "current_out_price": 10.0, "healing_model": "gpt-5.6-terra", "healing_in_price": 2.0, "healing_out_price": 8.0, "savings_pct": 20.0},
                {"tier": "CHALLENGER", "current_model": "gpt-5.6-sol", "current_in_price": 5.0, "current_out_price": 20.0, "healing_model": "gpt-5.6-sol", "healing_in_price": 4.5, "healing_out_price": 18.0, "savings_pct": 10.0}
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

    # 동적 세션 선택 드롭다운 옵션 구성 (최근 활동 시간 내림차순 정렬)
    session_map = {}
    for r in all_raw_records:
        sid = r.get("session_id")
        if not sid or sid == "N/A":
            continue
        if sid not in session_map:
            session_map[sid] = {"id": sid, "last_dt": r.get("datetime"), "count": 0, "credit": 0.0}
        session_map[sid]["count"] += 1
        rc = r.get("real_credit")
        if rc is not None:
            session_map[sid]["credit"] += float(rc)
        else:
            session_map[sid]["credit"] += float(r.get("cost", 0)) / 0.20
        if r.get("datetime") and (session_map[sid]["last_dt"] is None or r.get("datetime") > session_map[sid]["last_dt"]):
            session_map[sid]["last_dt"] = r.get("datetime")
    
    sorted_sessions = sorted(session_map.values(), key=lambda x: x["last_dt"] or datetime.min, reverse=True)
    
    session_options_html = '<option value="ALL" ' + ('selected' if not target_session or target_session == 'ALL' else '') + '>🌐 전체 세션 (All Sessions)</option>'
    if sorted_sessions:
        session_options_html += '<option value="LATEST" ' + ('selected' if target_session == 'LATEST' else '') + '>🔥 최신 활성 세션 (Current Active)</option>'
    
    for idx, s in enumerate(sorted_sessions):
        sid = s["id"]
        s_short = sid[:8] if len(sid) > 8 else sid
        time_str = s["last_dt"].strftime("%m-%d %H:%M") if s["last_dt"] else "N/A"
        is_latest = (idx == 0)
        prefix = "🔥 [최신] " if is_latest else ""
        label = f"{prefix}{time_str} | {s_short} ({s['count']}턴 · {s['credit']:.2f} Cr)"
        selected_attr = 'selected' if target_session == sid else ''
        session_options_html += f'<option value="{sid}" {selected_attr}>{label}</option>'

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

    try:
        try:
            from tierbridge.version import get_version_info
        except ImportError:
            from src.tierbridge.version import get_version_info
        app_version_tag = get_version_info().get("tag", "v0.1.1")
    except Exception:
        app_version_tag = "v0.1.1"

    # Client-side JavaScript 처리를 위한 원본 JSON 데이터 구성
    client_records = []
    for r in all_raw_records:
        client_records.append({
            "timestamp": r.get("timestamp") or (r["datetime"].strftime("%Y-%m-%d %H:%M:%S") if r.get("datetime") else "N/A"),
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
            "cost": r["cost"],
            "real_credit": r.get("real_credit"),
            "credits": r.get("credits", r["cost"] / 0.20)
        })
    client_records_json = json.dumps(client_records)

    try:
        try:
            from tierbridge.memory_handler import MemoryHandler
        except ImportError:
            from src.tierbridge.memory_handler import MemoryHandler
        initial_memories = MemoryHandler.get_recent_memories(limit=100)
        initial_mem_stats = MemoryHandler.get_memory_stats()
        initial_graph_data = MemoryHandler.get_graph_data(limit_nodes=60)
        initial_top_edges = MemoryHandler.get_top_weighted_edges(limit=10)
    except Exception:
        initial_memories = []
        initial_mem_stats = {"total_memories": 0, "total_tags": 0, "code_modified_count": 0, "max_edge_weight": 1.0, "structured_rate": 100.0}
        initial_graph_data = {"nodes": [], "edges": []}
        initial_top_edges = []

    client_memories_json = json.dumps(initial_memories)
    client_mem_stats_json = json.dumps(initial_mem_stats)
    client_graph_data_json = json.dumps(initial_graph_data)
    client_top_edges_json = json.dumps(initial_top_edges)
    
    has_healing_banner = healing_status.get("has_new_healing", False)
    banner_hidden_class = "" if has_healing_banner else "hidden"

    html_content = f"""<!DOCTYPE html>
<html lang="ko" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TierBridge Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            darkMode: 'class'
        }}
    </script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
    <script src="https://cdn.jsdelivr.net/npm/markmap-view@0.15.4"></script>
    <script src="https://cdn.jsdelivr.net/npm/markmap-lib@0.15.4"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        body {{ font-family: 'Inter', sans-serif; transition: background-color 0.25s ease, color 0.25s ease; }}
        
        /* Dark Theme Default */
        html.dark body {{ background-color: #0b0f19; color: #f1f5f9; }}
        html.dark .glass-card {{ background: rgba(15, 23, 42, 0.78); backdrop-filter: blur(12px); border: 1px solid rgba(51, 65, 85, 0.5); }}
        
        /* Light Theme Adaptation */
        html.light body {{ background-color: #f8fafc !important; color: #0f172a !important; }}
        html.light .glass-card {{ 
            background: rgba(255, 255, 255, 0.96) !important; 
            border: 1px solid #e2e8f0 !important; 
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05) !important; 
        }}
        html.light header {{ border-color: #e2e8f0 !important; }}
        html.light p.text-slate-400, html.light .text-slate-400 {{ color: #64748b !important; }}
        html.light h1, html.light h2, html.light h3 {{ color: #0f172a !important; }}
        html.light table thead tr, html.light tr[class*="bg-slate-800"], html.light tr[class*="bg-slate-900"] {{ 
            background-color: #f1f5f9 !important; 
            border-color: #e2e8f0 !important; 
            color: #475569 !important; 
        }}
        html.light table th {{ color: #475569 !important; }}
        html.light table tbody tr {{ border-color: #f1f5f9 !important; }}
        html.light table tbody tr:hover {{ background-color: rgba(241, 245, 249, 0.9) !important; }}
        html.light table td {{ color: #1e293b !important; }}
        
        /* Form Controls & Fields in Light Mode */
        html.light input[type="text"], html.light input, html.light select {{ 
            background-color: #ffffff !important; 
            color: #0f172a !important; 
            border-color: #cbd5e1 !important; 
        }}
        html.light select option {{
            background-color: #ffffff !important;
            color: #0f172a !important;
        }}
        html.light input::placeholder {{
            color: #94a3b8 !important;
        }}
        
        /* Container and Field Backgrounds in Light Mode */
        html.light .bg-slate-900, html.light .bg-slate-950, html.light .bg-slate-800,
        html.light [class*="bg-slate-900"], html.light [class*="bg-slate-950"], html.light [class*="bg-slate-800"] {{ 
            background-color: #ffffff !important; 
            border-color: #cbd5e1 !important; 
        }}
        
        /* Segmented Tab Bars and Pill Containers in Light Mode */
        html.light .inline-flex[class*="bg-slate-900"] {{
            background-color: #e2e8f0 !important;
            border-color: #cbd5e1 !important;
        }}
        html.light .border-slate-800, html.light .border-slate-700, html.light [class*="border-slate-700"] {{ 
            border-color: #e2e8f0 !important; 
        }}
        html.light .divide-slate-800 > :not([hidden]) ~ :not([hidden]) {{
            border-color: #e2e8f0 !important;
        }}
        html.light .text-slate-100, html.light .text-slate-200 {{ color: #0f172a !important; }}
        html.light .text-slate-300 {{ color: #334155 !important; }}
        
        /* Memory View Card Background Gradient Adaptation */
        html.light [class*="from-slate-900"], html.light [class*="via-slate-900"], html.light [class*="via-slate-950"], html.light [class*="to-purple-950"] {{
            background: #ffffff !important;
        }}
        html.light #memSearchResults {{
            background-color: #f8fafc !important;
        }}
        
        #memoryGraphCanvas div.vis-network:focus, #expandedMemoryGraphCanvas div.vis-network:focus {{ outline: none; }}
        
        /* Markmap & Thought Tree Containers */
        html.dark #expandedMarkmapContainer, html.dark #expandedMemoryGraphCanvas, html.dark #memoryGraphCanvas {{
            background-color: #020617 !important;
            border-color: #1e293b !important;
        }}
        html.light #expandedMarkmapContainer, html.light #expandedMemoryGraphCanvas, html.light #memoryGraphCanvas {{
            background-color: #ffffff !important;
            border-color: #cbd5e1 !important;
        }}
        
        html.light #expandedGraphModal {{
            background-color: rgba(248, 250, 252, 0.98) !important;
            color: #0f172a !important;
        }}
        html.light #expandedGraphModal h2, html.light #expandedGraphModal h3 {{
            color: #0f172a !important;
        }}
        html.light #expandedGraphModal .border-slate-800 {{
            border-color: #e2e8f0 !important;
        }}
        html.light #expandedGraphModal .bg-slate-900 {{
            background-color: #f1f5f9 !important;
            border-color: #cbd5e1 !important;
            color: #0f172a !important;
        }}
        html.light #expandedGraphModal .text-slate-400 {{
            color: #64748b !important;
        }}
        
        /* Markmap Text & Element Theme Adaptation */
        #markmapSvg {{ width: 100%; height: 100%; }}
        #markmapSvg text {{ font-family: 'Inter', Pretendard, -apple-system, sans-serif !important; font-weight: 500; font-size: 12px; }}
        html.dark #markmapSvg text, html.dark #markmapSvg div, html.dark #markmapSvg span {{ fill: #f1f5f9 !important; color: #f1f5f9 !important; }}
        html.light #markmapSvg text, html.light #markmapSvg div, html.light #markmapSvg span {{ fill: #0f172a !important; color: #0f172a !important; }}
        html.dark #markmapSvg h1, html.dark #markmapSvg h2, html.dark #markmapSvg h3, html.dark #markmapSvg strong, html.dark #markmapSvg b {{ color: #f8fafc !important; }}
        html.light #markmapSvg h1, html.light #markmapSvg h2, html.light #markmapSvg h3, html.light #markmapSvg strong, html.light #markmapSvg b {{ color: #0f172a !important; }}
        html.dark #markmapSvg li, html.dark #markmapSvg p {{ color: #cbd5e1 !important; }}
        html.light #markmapSvg li, html.light #markmapSvg p {{ color: #334155 !important; }}
        
        #markmapSvg circle {{ cursor: pointer; stroke-width: 2px; }}
        html.dark #markmapSvg circle {{ stroke: #a855f7 !important; fill: #0b0f19 !important; }}
        html.light #markmapSvg circle {{ stroke: #7c3aed !important; fill: #ffffff !important; }}
        
        #markmapSvg line, #markmapSvg path {{ stroke-linecap: round; }}
        html.dark #markmapSvg line, html.dark #markmapSvg path {{ stroke: #818cf8 !important; }}
        html.light #markmapSvg line, html.light #markmapSvg path {{ stroke: #6366f1 !important; }}
        
        .tb-node-link {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 1px 7px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
            cursor: pointer;
            text-decoration: none;
            margin-left: 6px;
            transition: all 0.2s ease;
        }}
        html.dark .tb-node-link {{
            background: rgba(168, 85, 247, 0.25);
            color: #d8b4fe;
            border: 1px solid rgba(168, 85, 247, 0.5);
        }}
        html.dark .tb-node-link:hover {{
            background: rgba(168, 85, 247, 0.5);
            color: #ffffff;
            box-shadow: 0 0 8px rgba(168, 85, 247, 0.6);
        }}
        html.light .tb-node-link {{
            background: rgba(147, 51, 234, 0.15) !important;
            color: #6b21a8 !important;
            border: 1px solid rgba(147, 51, 234, 0.45) !important;
        }}
        html.light .tb-node-link:hover {{
            background: rgba(147, 51, 234, 0.25) !important;
            color: #4c1d95 !important;
        }}
    </style>
</head>
<body class="text-slate-100 min-h-screen p-6 md:p-10">

    <!-- Header -->
    <header class="flex flex-col md:flex-row md:items-center md:justify-between mb-8 pb-6 border-b border-slate-800 gap-4">
        <div>
            <div class="flex items-center gap-3 mb-1">
                <span class="p-2.5 bg-indigo-600/20 border border-indigo-500/30 text-indigo-400 rounded-xl">
                    <i class="fa-solid fa-chart-line text-xl"></i>
                </span>
                <h1 class="text-2xl md:text-3xl font-bold bg-gradient-to-r from-sky-400 via-indigo-300 to-emerald-400 bg-clip-text text-transparent flex items-center gap-2.5">
                    <span>TierBridge Dashboard</span>
                    <span id="appVersionBadge" class="text-xs px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono font-bold align-middle shadow-sm">{app_version_tag}</span>
                </h1>
            </div>
            <p class="text-slate-400 text-sm pl-12">
                Codex Enterprise AI 사용량, 토큰 소모 및 모델 관리 대시보드
            </p>
        </div>
        
        <!-- Controls: Dynamic Month, Session, Model Version, Theme Switcher & Live Indicator -->
        <div class="flex flex-wrap items-center gap-2.5">
            <!-- 🎨 3-Segment Theme Switcher (Dark / Light / System) -->
            <div class="inline-flex p-1 bg-slate-900/90 border border-slate-700/60 rounded-xl shadow-lg gap-0.5">
                <button id="themeBtnDark" onclick="setTheme('dark')" title="어두운 테마 (Dark)"
                        class="px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200">
                    <i class="fa-solid fa-moon text-xs"></i>
                    <span class="hidden sm:inline">어두운</span>
                </button>
                <button id="themeBtnLight" onclick="setTheme('light')" title="밝은 테마 (Light)"
                        class="px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200">
                    <i class="fa-solid fa-sun text-xs text-amber-500"></i>
                    <span class="hidden sm:inline">밝은</span>
                </button>
                <button id="themeBtnSystem" onclick="setTheme('system')" title="시스템 기본 (System OS)"
                        class="px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200">
                    <i class="fa-solid fa-laptop text-xs text-sky-400"></i>
                    <span class="hidden sm:inline">기본</span>
                </button>
            </div>

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
                        class="bg-slate-900 text-purple-300 font-mono text-xs font-bold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-purple-400 cursor-pointer max-w-[240px] md:max-w-[320px] truncate">
                    {session_options_html}
                </select>
            </div>

            <!-- Model Version Selector -->
            <div class="flex items-center gap-2 bg-slate-800/90 border border-sky-500/40 px-3 py-1.5 rounded-xl shadow-lg">
                <i class="fa-solid fa-code-branch text-sky-400 text-sm"></i>
                <span class="text-xs font-semibold text-slate-300">버전:</span>
                <select id="versionSelect" onchange="switchModelVersion(this.value)"
                        class="bg-slate-900 text-sky-300 font-mono text-xs font-bold rounded-lg px-2.5 py-1 border border-slate-700 focus:outline-none focus:border-sky-400 cursor-pointer">
                    {version_options_html}
                </select>
            </div>

            <!-- Git Pull / Version Sync Badge -->
            <div id="gitStatusBadge" class="hidden md:flex items-center gap-1.5 bg-slate-800/80 border border-slate-700/60 px-2.5 py-1.5 rounded-xl text-slate-400 text-xs font-mono cursor-pointer hover:bg-slate-700/60 transition-all" onclick="openGitPullModal()" title="Git 원격 동기화 상태 확인">
                <i class="fa-solid fa-code-pull-request text-indigo-400"></i>
                <span id="gitStatusText">Git Checking...</span>
            </div>

            <!-- Interactive Live Sync Control Toolbar -->
            <div class="relative inline-flex items-center bg-slate-800/90 border border-emerald-500/40 rounded-xl shadow-lg p-0.5 gap-1">
                <!-- Manual Refresh Button -->
                <button onclick="triggerManualRefresh()" id="manualRefreshBtn" title="지금 즉시 데이터 갱신"
                        class="p-1.5 px-2 hover:bg-slate-700/80 rounded-lg text-emerald-400 hover:text-emerald-300 transition-all cursor-pointer">
                    <i id="manualRefreshIcon" class="fa-solid fa-rotate-right text-xs"></i>
                </button>
                <!-- Live Polling Badge / Dropdown Trigger -->
                <div id="liveSyncBadge" onclick="togglePollDropdown(event)" 
                     class="flex items-center gap-1.5 bg-emerald-950/70 border border-emerald-500/50 px-2.5 py-1 rounded-lg text-emerald-400 text-xs font-bold cursor-pointer hover:bg-emerald-900/60 transition-all">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    <span id="liveSyncBadgeText">5s Live</span>
                    <i class="fa-solid fa-chevron-down text-[10px] text-emerald-400/70 ml-0.5"></i>
                </div>
                <!-- Pause/Play Quick Toggle -->
                <button onclick="toggleLivePolling()" id="pollToggleBtn" title="자동 갱신 일시정지 / 재개"
                        class="p-1.5 px-2 hover:bg-slate-700/80 rounded-lg text-slate-400 hover:text-amber-300 transition-all cursor-pointer">
                    <i id="pollToggleIcon" class="fa-solid fa-pause text-xs"></i>
                </button>

                <!-- Polling Interval Dropdown Popover -->
                <div id="pollIntervalDropdown" class="hidden absolute top-full right-0 mt-2 z-50 w-56 p-2 rounded-2xl bg-slate-900/95 border border-slate-700 shadow-2xl backdrop-blur-xl text-xs space-y-1">
                    <div class="px-2.5 py-1.5 font-bold text-slate-300 border-b border-slate-800 flex items-center justify-between">
                        <span>⏱️ 자동 갱신 주기</span>
                        <span class="text-[10px] text-slate-500 font-mono">localStorage 저장</span>
                    </div>
                    <button onclick="setPollInterval(3)" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800/80 flex items-center justify-between text-slate-200">
                        <span>⚡ 3초 (고속 동기화)</span>
                        <span id="pollCheck3" class="text-emerald-400 text-xs font-bold hidden">✓</span>
                    </button>
                    <button onclick="setPollInterval(5)" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800/80 flex items-center justify-between text-slate-200">
                        <span>🎯 5초 (기본 권장)</span>
                        <span id="pollCheck5" class="text-emerald-400 text-xs font-bold hidden">✓</span>
                    </button>
                    <button onclick="setPollInterval(10)" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800/80 flex items-center justify-between text-slate-200">
                        <span>🌱 10초 (저부하 모드)</span>
                        <span id="pollCheck10" class="text-emerald-400 text-xs font-bold hidden">✓</span>
                    </button>
                    <button onclick="setPollInterval(30)" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800/80 flex items-center justify-between text-slate-200">
                        <span>🌙 30초 (백그라운드)</span>
                        <span id="pollCheck30" class="text-emerald-400 text-xs font-bold hidden">✓</span>
                    </button>
                    <button onclick="setPollInterval(0)" class="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-slate-800/80 flex items-center justify-between text-amber-300">
                        <span>⏸️ 수동 갱신 (중지)</span>
                        <span id="pollCheck0" class="text-amber-400 text-xs font-bold hidden">✓</span>
                    </button>
                    <div class="pt-1.5 mt-1 border-t border-slate-800 px-1 flex items-center gap-1.5">
                        <span class="text-[11px] text-slate-400 whitespace-nowrap">직접 입력:</span>
                        <input id="customPollInput" type="number" min="1" max="3600" placeholder="초"
                               class="w-14 bg-slate-950 border border-slate-700 rounded px-1.5 py-0.5 text-center font-mono text-emerald-400 text-xs focus:outline-none focus:border-emerald-500"
                               onkeydown="if(event.key==='Enter') applyCustomPollInterval()">
                        <button onclick="applyCustomPollInterval()" class="px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[11px] font-bold">적용</button>
                    </div>
                </div>
            </div>

            <!-- Healing Factor Demo Sample Test Button -->
            <button onclick="openHealingModal()"
                    class="px-3 py-1.5 bg-gradient-to-r from-purple-600/30 to-indigo-600/30 border border-purple-400/50 text-purple-200 text-xs font-bold rounded-xl shadow-lg hover:bg-purple-600/40 transition-all flex items-center gap-1.5">
                <i class="fa-solid fa-vial-circle-check text-purple-300"></i>
                <span>🧪 힐링 데모</span>
            </button>

            <!-- Healing Notice Button -->
            <button id="healingNoticeBtn" onclick="openHealingModal()"
                    class="{banner_hidden_class} px-3 py-1.5 bg-gradient-to-r from-emerald-500/20 to-teal-500/20 border border-emerald-500/50 text-emerald-300 text-xs font-bold rounded-xl shadow-lg hover:bg-emerald-500/30 transition-all flex items-center gap-1.5">
                <i class="fa-solid fa-kit-medical text-emerald-400"></i>
                <span>💡 신규 모델!</span>
            </button>
        </div>
    </header>

    <!-- Modern Segmented Pill Tab Bar (Shadcn / Vercel Premium Style) -->
    <div class="flex items-center justify-between mb-8 pb-2">
        <div class="inline-flex p-1.5 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-inner backdrop-blur-md gap-1.5">
            <button id="tabBtnUsage" onclick="switchDashboardTab('usage')"
                    class="px-5 py-2.5 rounded-xl text-xs font-bold transition-all duration-300 flex items-center gap-2.5 cursor-pointer bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25 border border-indigo-400/30">
                <i class="fa-solid fa-chart-line text-sm"></i>
                <span>📊 AI 사용량 & 크레딧 관제</span>
            </button>
            <button id="tabBtnMemory" onclick="switchDashboardTab('memory')"
                    class="px-5 py-2.5 rounded-xl text-xs font-semibold transition-all duration-300 flex items-center gap-2.5 cursor-pointer text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent">
                <i class="fa-solid fa-brain text-sm text-purple-400"></i>
                <span>🧠 Giyeok 장기 기억저장소 & 생각나무</span>
                <span id="memTabCountBadge" class="text-[10px] px-2 py-0.5 bg-purple-500/20 text-purple-300 rounded-full font-mono font-bold border border-purple-500/30">0건</span>
            </button>
        </div>
        <div class="hidden md:flex items-center gap-2 text-xs text-slate-400 font-mono">
            <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>Direct SQLite ✕ In-process Live Graph</span>
        </div>
    </div>

    <!-- Tab 1: AI Usage & Credit Analytics View -->
    <div id="usageView">
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

    <!-- Enterprise Live Balance Bar -->
    <div id="enterpriseBalanceWidget" class="mb-8 p-5 rounded-2xl glass-card border border-sky-500/40 bg-gradient-to-r from-slate-900 via-slate-900 to-sky-950/40 flex flex-col lg:flex-row items-center justify-between gap-6">
        <div class="flex items-center gap-4">
            <span class="p-3.5 bg-sky-500/20 border border-sky-500/40 text-sky-400 rounded-2xl text-2xl">
                <i class="fa-solid fa-building-columns"></i>
            </span>
            <div>
                <div class="flex items-center gap-2">
                    <h3 class="text-sm font-bold text-slate-100 flex items-center gap-2">
                        ChatGPT Enterprise Live Spend Control
                    </h3>
                    <span id="entPlanBadge" class="text-xs px-2.5 py-0.5 bg-sky-500/20 text-sky-300 rounded-full font-mono font-bold">Business Plan</span>
                </div>
                <p class="text-xs text-slate-400 mt-1" id="entAccountEmail">
                    계정: <span class="text-slate-300 font-mono">86lyh@hanatour.com</span> | 리셋 주기: <span id="entResetAt" class="text-emerald-400 font-bold">매월 1일</span>
                </p>
            </div>
        </div>

        <div class="flex-1 max-w-xl w-full">
            <div class="flex justify-between text-xs font-semibold mb-1.5">
                <span class="text-slate-300">실제 소모: <span id="entUsedCredits" class="text-indigo-400 font-mono font-bold">- Cr</span></span>
                <span class="text-slate-300">실제 잔여: <span id="entRemainingCredits" class="text-emerald-400 font-mono font-bold">- Cr</span> / <span id="entLimitCredits" class="text-slate-400 font-mono">- Cr</span></span>
            </div>
            <div class="w-full bg-slate-800 rounded-full h-3.5 p-0.5 border border-slate-700 overflow-hidden">
                <div id="entProgressBar" class="bg-gradient-to-r from-emerald-500 via-sky-400 to-indigo-500 h-2.5 rounded-full transition-all duration-500" style="width: 0%;"></div>
            </div>
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
            <div class="flex items-center justify-between mb-2">
                <div class="text-xs font-semibold uppercase tracking-wider text-emerald-400">다운스케일링 누적 절감액</div>
                <button onclick="openSavingsInfoModal()" class="text-emerald-400/80 hover:text-emerald-200 transition-colors p-1 rounded-lg hover:bg-emerald-500/20 flex items-center justify-center cursor-pointer" title="절감액 산출 기준 및 수식 안내">
                    <i class="fa-solid fa-circle-info text-sm"></i>
                </button>
            </div>
            <div class="text-3xl font-extrabold text-emerald-300 font-mono mb-1" id="kpiSavingsUsd">$0.00</div>
            <div class="text-xs text-emerald-400/80" id="kpiSavingsCredits">약 0.0 Cr 크레딧 아낌</div>
            <div class="absolute -right-3 -bottom-3 text-emerald-400/10 text-6xl pointer-events-none"><i class="fa-solid fa-shield-halved"></i></div>
        </div>
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
        <!-- Daily Trend Line Chart -->
        <div class="lg:col-span-2 glass-card p-6 rounded-2xl flex flex-col justify-between">
            <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
                <div>
                    <h2 id="timelineChartTitle" class="text-base font-semibold text-slate-200 flex items-center gap-2">
                        <i id="timelineChartIcon" class="fa-solid fa-chart-area text-sky-400"></i> <span id="timelineChartTitleText">선택 기간 일자별 추이 (Daily Trend)</span>
                    </h2>
                    <span id="timelineChartSubText" class="text-xs text-slate-400 font-mono">Kibana Live Timeline</span>
                </div>

                <!-- Interactive Chart Control Toolbars -->
                <div class="flex items-center gap-2 flex-wrap">
                    <!-- Metric Focus Switcher (Dual / Credits / Tokens / Cumulative) -->
                    <div id="chartMetricFocusGroup" class="inline-flex p-1 bg-slate-900/90 border border-slate-700/70 rounded-xl shadow-inner gap-0.5 text-xs">
                        <button id="chartFocusDual" onclick="setChartMetricFocus('dual')" 
                                class="px-2.5 py-1 rounded-lg font-bold transition-all bg-indigo-600 text-white shadow-sm cursor-pointer" title="크레딧과 토큰 함께 보기">
                            ✨ 듀얼 뷰
                        </button>
                        <button id="chartFocusCredit" onclick="setChartMetricFocus('credit')" 
                                class="px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer" title="크레딧 소모량만 집중 보기">
                            💳 크레딧만
                        </button>
                        <button id="chartFocusToken" onclick="setChartMetricFocus('token')" 
                                class="px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer" title="토큰 소모량만 집중 보기">
                            📦 토큰만
                        </button>
                        <button id="chartFocusCumulative" onclick="setChartMetricFocus('cumulative')" 
                                class="px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer" title="누적 소모 곡선 보기">
                            📈 누적 추이
                        </button>
                    </div>

                    <!-- Single Session Filter Mode (Pairing vs Model Only vs Raw All) -->
                    <div id="sessionTurnFilterGroup" class="hidden inline-flex p-1 bg-slate-900/90 border border-purple-500/40 rounded-xl shadow-inner gap-0.5 text-xs">
                        <button id="turnFilterMerged" onclick="setSessionTurnFilter('merged')" 
                                class="px-2.5 py-1 rounded-lg font-bold transition-all bg-purple-600 text-white shadow-sm cursor-pointer" title="1턴 단위 통합 (분류기+모델 페어링으로 파동 제거)">
                            🎯 1턴 통합
                        </button>
                        <button id="turnFilterModel" onclick="setSessionTurnFilter('model')" 
                                class="px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer" title="메인 에이전트 모델 턴만 보기">
                            🤖 모델만
                        </button>
                        <button id="turnFilterAll" onclick="setSessionTurnFilter('all')" 
                                class="px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer" title="분류기 포함 원시 턴 전체 보기">
                            🔍 원시 전체
                        </button>
                    </div>
                </div>
            </div>
            <div class="h-64 relative">
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

    <!-- Session Turn-by-Turn Live Stream (Visible ONLY when specific session is selected) -->
    <div id="sessionTurnsSection" class="hidden glass-card p-6 rounded-2xl mb-8 border border-purple-500/40 bg-gradient-to-br from-slate-900 via-slate-900 to-purple-950/20">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5 pb-4 border-b border-slate-800">
            <div>
                <div class="flex items-center gap-2">
                    <span class="p-2 bg-purple-500/20 text-purple-400 rounded-xl text-lg">
                        <i class="fa-solid fa-list-ol"></i>
                    </span>
                    <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                        선택 세션 턴별 프롬프트 실시간 타임라인
                        <span id="sessionTurnsBadge" class="text-xs px-2.5 py-0.5 bg-purple-500/20 text-purple-300 rounded-full font-mono font-bold">0 턴</span>
                    </h2>
                </div>
                <p class="text-xs text-slate-400 mt-1" id="sessionTurnsDesc">
                    세션 내 발생한 모든 질의 턴과 에이전트 서브스텝 프롬프트, 모델 라우팅 등급 및 소모 수치를 시간순으로 실시간 표시합니다.
                </p>
            </div>
            <div class="text-xs font-mono text-slate-400 bg-slate-800/80 px-3 py-1.5 rounded-xl border border-slate-700">
                세션 ID: <span id="sessionTurnsSid" class="text-purple-300 font-bold">-</span>
            </div>
        </div>

        <div class="overflow-x-auto max-h-96 overflow-y-auto pr-1">
            <table class="w-full text-left border-collapse" id="sessionTurnsTable">
                <thead class="sticky top-0 bg-slate-900/95 backdrop-blur-md z-10">
                    <tr class="text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700">
                        <th class="px-3 py-2.5 rounded-tl-lg font-mono">Turn</th>
                        <th class="px-3 py-2.5">발생 시각</th>
                        <th class="px-3 py-2.5 text-center">라우팅 등급</th>
                        <th class="px-3 py-2.5">프롬프트 전문 / 서브스텝 요약</th>
                        <th class="px-3 py-2.5 text-right">In / Out 토큰</th>
                        <th class="px-3 py-2.5 text-right">소모 토큰</th>
                        <th class="px-3 py-2.5 text-right rounded-tr-lg">소모 크레딧</th>
                    </tr>
                </thead>
                <tbody id="sessionTurnsTableBody" class="divide-y divide-slate-800 text-xs">
                    <!-- Populated dynamically via JS -->
                </tbody>
            </table>
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
    </div><!-- end #usageView -->

    <!-- Tab 2: Giyeok Long-term Memory Explorer View -->
    <div id="memoryView" class="hidden">
        <!-- Memory KPI Cards Row -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="glass-card p-6 rounded-2xl border border-purple-500/30">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-purple-300">누적 지식 에피소드</span>
                    <i class="fa-solid fa-boxes-stacked text-purple-400"></i>
                </div>
                <div class="text-2xl font-bold text-slate-100 font-mono" id="kpiMemTotal">0 <span class="text-sm font-normal text-slate-400">Episodes</span></div>
                <p class="text-xs text-slate-400 mt-2">Problem-Solution 3단 구조화 보존</p>
            </div>

            <div class="glass-card p-6 rounded-2xl border border-emerald-500/30">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-emerald-300">기억 회수 적중 (Recall Hits)</span>
                    <i class="fa-solid fa-bolt text-emerald-400"></i>
                </div>
                <div class="text-2xl font-bold text-emerald-400 font-mono" id="kpiMemRecallHits">0 <span class="text-sm font-normal text-slate-400">Hits</span></div>
                <p class="text-xs text-slate-400 mt-2">초고속 50ms 샌드박스 사전 회수</p>
            </div>

            <div class="glass-card p-6 rounded-2xl border border-sky-500/30">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-sky-300">기억 주입 절감 크레딧</span>
                    <i class="fa-solid fa-piggy-bank text-sky-400"></i>
                </div>
                <div class="text-2xl font-bold text-sky-300 font-mono" id="kpiMemSavedCredits">0.00 <span class="text-sm font-normal text-slate-400">Cr</span></div>
                <p class="text-xs text-slate-400 mt-2">다운스케일 기억 보조 ROI 누적</p>
            </div>

            <div class="glass-card p-6 rounded-2xl border border-amber-500/30">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-semibold text-amber-300">최고 엣지 강화 가중치</span>
                    <i class="fa-solid fa-fire text-amber-400"></i>
                </div>
                <div class="text-2xl font-bold text-amber-300 font-mono" id="kpiMemMaxWeight">1.00 <span class="text-sm font-normal text-slate-400">x</span></div>
                <p class="text-xs text-slate-400 mt-2">비용/난이도/LOC 승격 최대 배수</p>
            </div>
        </div>

        <!-- 2-Column Side-by-Side Section: Recall Explorer (Left) & Compact Thought-Tree Mini Graph (Right) -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8 items-start">
            
            <!-- Left Column: Semantic Memory Search (Recall Explorer) -->
            <div class="lg:col-span-7 glass-card p-6 rounded-2xl border border-purple-500/40 bg-gradient-to-br from-slate-900 via-slate-900 to-purple-950/20 flex flex-col h-[520px]">
                <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4 pb-3 border-b border-slate-800">
                    <div>
                        <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
                            <i class="fa-solid fa-magnifying-glass-location text-purple-400"></i>
                            연관 기억 실시간 시맨틱 검색기 (Recall Explorer)
                        </h2>
                        <p class="text-xs text-slate-400 mt-0.5">
                            검색 카드를 클릭하면 우측 생각나무 노드로 자동 포커스 이동합니다.
                        </p>
                    </div>
                </div>

                <div class="flex items-center gap-2 mb-3">
                    <input type="text" id="memSearchInput" placeholder="질의어/에러문구/도메인 검색 (예: Lombok, 쿠폰, DTO, auth)..." 
                           oninput="onMemorySearchRealtime(this.value)"
                           onkeyup="onMemorySearchInput(event)"
                           class="bg-slate-900/90 border border-slate-700 text-slate-200 text-xs rounded-xl px-4 py-2.5 focus:outline-none focus:border-purple-400 flex-1">
                    <button onclick="performMemorySearch()"
                            class="px-4 py-2.5 bg-purple-600 hover:bg-purple-500 text-slate-100 text-xs font-bold rounded-xl shadow-lg transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-search"></i>
                        <span>검색</span>
                    </button>
                </div>

                <!-- Search Results Scroll Area -->
                <div id="memSearchResults" class="space-y-3 flex-1 overflow-y-auto pr-1">
                    <div class="text-center py-10 text-xs text-slate-500 font-mono">
                        💡 검색어를 입력하고 엔터를 누르거나 [검색] 버튼을 클릭하세요.
                    </div>
                </div>
            </div>

            <!-- Right Column: Compact Thought-Tree Mini Graph Canvas -->
            <div class="lg:col-span-5 glass-card p-6 rounded-2xl border border-purple-500/40 bg-gradient-to-br from-slate-900 via-slate-950 to-purple-950/20 flex flex-col h-[520px]">
                <div class="flex items-center justify-between gap-2 mb-3 pb-3 border-b border-slate-800">
                    <div>
                        <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
                            <i class="fa-solid fa-network-wired text-purple-400"></i>
                            🌿 생각나무 미니 캔버스
                        </h2>
                        <p class="text-[11px] text-slate-400 mt-0.5">
                            노드 클릭: 상세/소각 모달
                        </p>
                    </div>
                    <div class="flex items-center gap-1.5">
                        <button onclick="fitMemoryGraph()" title="화면 중앙 맞춤"
                                class="px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1 cursor-pointer">
                            <i class="fa-solid fa-arrows-to-eye"></i>
                        </button>
                        <button id="toggleMiniPhysicsBtn" onclick="toggleGraphPhysics()" title="물리 시뮬레이션 토글"
                                class="px-2.5 py-1.5 bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 text-xs font-bold rounded-xl border border-purple-500/40 transition-all flex items-center gap-1 cursor-pointer">
                            <i class="fa-solid fa-atom"></i>
                        </button>
                        <button onclick="openExpandedGraphModal()" title="전체 화면으로 확대 보기"
                                class="px-3 py-1.5 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-bold rounded-xl shadow-lg transition-all flex items-center gap-1.5 cursor-pointer">
                            <i class="fa-solid fa-expand"></i>
                            <span>확대</span>
                        </button>
                    </div>
                </div>

                <!-- Mini Graph Canvas -->
                <div id="memoryGraphCanvas" class="w-full flex-1 rounded-2xl bg-slate-950/90 border border-slate-800 relative flex items-center justify-center overflow-hidden">
                    <div class="text-slate-500 text-xs font-mono animate-pulse">
                        <i class="fa-solid fa-circle-notch fa-spin mr-2"></i> 생각나무 그래프 캔버스 렌더링 중...
                    </div>
                </div>

                <!-- Mini Legend -->
                <div class="flex items-center justify-between mt-3 pt-2 border-t border-slate-800/80 text-[10px] text-slate-400">
                    <div class="flex items-center gap-2">
                        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-500"></span> GOLD</span>
                        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-cyan-500"></span> PLATINUM</span>
                        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-slate-400"></span> SILVER</span>
                        <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-800"></span> BRONZE</span>
                    </div>
                    <span class="font-mono text-purple-300">클릭 시 포커스</span>
                </div>
            </div>

        </div>

        <!-- Top-Ranked Knowledge Graph Table Section (TOP 10 엣지 가중치) -->
        <div class="glass-card p-6 rounded-2xl mb-8 border border-slate-800">
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5 pb-4 border-b border-slate-800">
                <div>
                    <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                        <i class="fa-solid fa-trophy text-yellow-400"></i>
                        🏆 확정된 고가치 지식 엣지 가중치 TOP 10 랭킹 (Top-Ranked Knowledge)
                    </h2>
                    <p class="text-xs text-slate-400 mt-1">
                        비용($), 의사결정 등급 및 코드 수정량(LOC)에 의해 SQLite edges 테이블에 가중치(1.0x ~ 10.0x)가 승격된 고가치 지식입니다.
                    </p>
                </div>
                <span class="text-xs px-3 py-1.5 bg-yellow-500/20 text-yellow-300 font-mono font-bold rounded-xl border border-yellow-500/30">
                    Step 3 Reinforcer Active
                </span>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse" id="topEdgesTable">
                    <thead>
                        <tr class="bg-slate-800/80 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700">
                            <th class="px-4 py-3 rounded-tl-xl font-mono">Rank</th>
                            <th class="px-4 py-3">Source Node ID</th>
                            <th class="px-4 py-3 text-center">등급</th>
                            <th class="px-4 py-3 text-right">LOC</th>
                            <th class="px-4 py-3 text-right">비용 ($)</th>
                            <th class="px-4 py-3 text-right font-bold text-amber-300">승격 가중치</th>
                            <th class="px-4 py-3">Target Node</th>
                            <th class="px-4 py-3 rounded-tr-xl">문제 및 요구사항 요약</th>
                        </tr>
                    </thead>
                    <tbody id="topEdgesTableBody" class="divide-y divide-slate-800 text-xs">
                        <!-- Populated dynamically via JS -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Live Memory Stream Table with Neuralizer Action -->
        <div class="glass-card p-6 rounded-2xl mb-8 border border-slate-800">
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <div>
                    <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                        <i class="fa-solid fa-database text-sky-400"></i>
                        실시간 적재 기억 에피소드 스트림 (Live Memory Stream)
                    </h2>
                    <p class="text-xs text-slate-400 mt-1">
                        하네스 퀄리티 게이트를 통과하여 memory.db에 축적된 3단 지식 에피소드 목록입니다. 불필요한 노드는 [소각] 버튼으로 안전하게 정밀 삭제할 수 있습니다.
                    </p>
                </div>
                <span class="text-xs px-3 py-1.5 bg-purple-500/20 text-purple-300 font-mono font-bold rounded-xl border border-purple-500/30">
                    Direct SQLite / In-process
                </span>
            </div>

            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse" id="memoryStreamTable">
                    <thead>
                        <tr class="bg-slate-800/80 text-slate-400 text-xs uppercase tracking-wider border-b border-slate-700">
                            <th class="px-4 py-3 rounded-tl-xl font-mono">ID</th>
                            <th class="px-4 py-3">Session ID</th>
                            <th class="px-4 py-3 text-center">등급</th>
                            <th class="px-4 py-3">📌 문제 및 요구사항</th>
                            <th class="px-4 py-3">💡 해결 등급 / 코드</th>
                            <th class="px-4 py-3">🏷️ 태그</th>
                            <th class="px-4 py-3 text-right">저장 시각</th>
                            <th class="px-4 py-3 text-center rounded-tr-xl">기억 관리</th>
                        </tr>
                    </thead>
                    <tbody id="memoryStreamTableBody" class="divide-y divide-slate-800 text-xs">
                        <!-- Populated dynamically via JS -->
                    </tbody>
                </table>
            </div>
        </div>
    </div><!-- end #memoryView -->

    <!-- Fullscreen Expanded Dual Viewport Modal -->
    <div id="expandedGraphModal" class="hidden fixed inset-0 z-50 bg-slate-950/95 backdrop-blur-xl flex flex-col p-4 md:p-6">
        <div class="flex flex-col lg:flex-row lg:items-center justify-between pb-4 mb-4 border-b border-slate-800 gap-4">
            <div class="flex items-center gap-3">
                <span class="p-2 bg-purple-500/20 border border-purple-500/30 text-purple-300 rounded-xl">
                    <i class="fa-solid fa-network-wired text-lg"></i>
                </span>
                <div>
                    <div class="flex flex-wrap items-center gap-3">
                        <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                            🧠 Giyeok 생각나무 연상 기억 탐색기
                        </h2>
                        <!-- 🌌🌿 Dual View Mode Segmented Tab Switcher -->
                        <div class="inline-flex p-1 bg-slate-900 border border-slate-700/80 rounded-xl gap-1 shadow-inner">
                            <button id="modalViewBtnNetwork" onclick="switchModalViewMode('network')"
                                    class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer bg-purple-600/30 text-purple-300 border border-purple-500/40">
                                <i class="fa-solid fa-circle-nodes"></i> 🌌 성단 네트워크 (vis)
                            </button>
                            <button id="modalViewBtnMarkmap" onclick="switchModalViewMode('markmap')"
                                    class="px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200 border border-transparent">
                                <i class="fa-solid fa-sitemap"></i> 🌿 생각나무 마인드맵 (Markmap)
                            </button>
                        </div>
                    </div>
                    <p class="text-xs text-slate-400 mt-1" id="modalViewDescription">
                        성단 뷰: 노드 크기(엣지 가중치), 연결 강도, 1-hop 하이라이트 • 마인드맵 뷰: 도메인별 문제 ➔ 해결책 접이식 브레인스토밍 트리
                    </p>
                </div>
            </div>
            
            <!-- Controls in Expanded Modal -->
            <div class="flex items-center gap-2 flex-wrap">
                <!-- Network specific controls -->
                <div id="modalNetworkControls" class="flex items-center gap-2">
                    <select id="modalGraphTierFilter" onchange="filterExpandedMemoryGraph()" 
                            class="bg-slate-900 border border-slate-700 text-slate-300 text-xs rounded-xl px-3 py-2 focus:outline-none focus:border-purple-400">
                        <option value="ALL">전체 등급 (All Tiers)</option>
                        <option value="GOLD">GOLD 노드만</option>
                        <option value="PLATINUM">PLATINUM 노드만</option>
                        <option value="SILVER">SILVER 노드만</option>
                        <option value="BRONZE">BRONZE 노드만</option>
                    </select>
                    <button onclick="zoomInNetwork()" title="확대 (Zoom In)"
                            class="px-2.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center cursor-pointer">
                        <i class="fa-solid fa-magnifying-glass-plus"></i>
                    </button>
                    <button onclick="zoomOutNetwork()" title="축소 (Zoom Out)"
                            class="px-2.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center cursor-pointer">
                        <i class="fa-solid fa-magnifying-glass-minus"></i>
                    </button>
                    <button onclick="fitExpandedMemoryGraph()" 
                            class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-arrows-to-eye"></i> 중앙 맞춤
                    </button>
                    <button id="toggleModalPhysicsBtn" onclick="toggleModalGraphPhysics()" 
                            class="px-3 py-2 bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 text-xs font-bold rounded-xl border border-purple-500/40 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-atom"></i> 물리엔진 끄기
                    </button>
                </div>

                <!-- Markmap specific controls (Hidden by default) -->
                <div id="modalMarkmapControls" class="hidden flex items-center gap-2">
                    <button onclick="zoomInMarkmap()" title="마인드맵 확대 (Zoom In)"
                            class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-emerald-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-magnifying-glass-plus"></i> 확대
                    </button>
                    <button onclick="zoomOutMarkmap()" title="마인드맵 축소 (Zoom Out)"
                            class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-magnifying-glass-minus"></i> 축소
                    </button>
                    <button onclick="fitMarkmapTree()" 
                            class="px-3 py-2 bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 text-xs font-bold rounded-xl border border-purple-500/40 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-expand"></i> 뷰 맞춤
                    </button>
                    <button onclick="expandAllMarkmap()" 
                            class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-emerald-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-folder-open"></i> 모두 펼치기
                    </button>
                    <button onclick="collapseAllMarkmap()" 
                            class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer">
                        <i class="fa-solid fa-folder"></i> 모두 접기
                    </button>
                </div>

                <button onclick="closeExpandedGraphModal()" 
                        class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold rounded-xl border border-slate-600 transition-all flex items-center gap-1.5 cursor-pointer ml-2">
                    <i class="fa-solid fa-xmark text-sm"></i> 닫기 (ESC)
                </button>
            </div>
        </div>

        <!-- Viewport 1: Fullscreen Network Canvas -->
        <div id="expandedMemoryGraphCanvas" class="w-full flex-1 rounded-2xl bg-slate-950/95 border border-slate-800 relative flex items-center justify-center overflow-hidden">
            <div class="text-slate-500 text-xs font-mono animate-pulse">
                <i class="fa-solid fa-circle-notch fa-spin mr-2"></i> 생각나무 고해상도 성단 캔버스 초기화 중...
            </div>
        </div>

        <!-- Viewport 2: Fullscreen Markmap Mindmap SVG Container -->
        <div id="expandedMarkmapContainer" class="hidden w-full flex-1 rounded-2xl bg-slate-950/95 border border-slate-800 relative overflow-hidden flex flex-col p-4">
            <svg id="markmapSvg" class="w-full h-full"></svg>
        </div>

        <!-- Expanded Footer Legend -->
        <div class="flex items-center justify-between pt-3 mt-3 border-t border-slate-800 text-xs text-slate-400">
            <div id="modalNetworkLegend" class="flex items-center gap-4">
                <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-amber-500"></span> GOLD</span>
                <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-cyan-500"></span> PLATINUM</span>
                <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-slate-400"></span> SILVER</span>
                <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-amber-800"></span> BRONZE</span>
            </div>
            <div id="modalMarkmapLegend" class="hidden font-mono text-emerald-400 text-xs">
                🌿 Markmap: 맥북 트랙패드 두 손가락 스크롤 줌 • 상단 [🔍 확대/축소/맞춤] • 원형 노드 클릭 접기/펼치기
            </div>
            <div class="font-mono text-purple-300 text-xs">
                💡 맥북 트랙패드 두 손가락 스크롤 / 핀치 줌 / 툴바 🔍 버튼 완벽 지원
            </div>
        </div>
    </div>

    <!-- Git Pull / Update Available Modal -->
    <div id="gitPullModal" class="hidden fixed inset-0 z-[70] bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass-card max-w-lg w-full p-6 rounded-3xl border border-amber-500/40 shadow-2xl relative bg-slate-900/95 max-h-[85vh] overflow-y-auto">
            <button onclick="closeGitPullModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-200 text-lg cursor-pointer">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <div class="flex items-center gap-3 mb-4 pr-8">
                <span class="p-2.5 bg-amber-500/20 border border-amber-500/40 text-amber-400 rounded-2xl text-xl">
                    <i class="fa-solid fa-code-pull-request"></i>
                </span>
                <div>
                    <h3 class="text-base font-bold text-slate-100 flex items-center gap-2">
                        Git 원격 저장소 동기화 상태
                    </h3>
                    <p class="text-xs text-slate-400">
                        브랜치: <span id="gitModalBranch" class="font-mono text-indigo-300 font-bold">main</span> | 상태: <span id="gitModalBehind" class="font-mono text-amber-400 font-bold">-</span>
                    </p>
                </div>
            </div>

            <div class="space-y-4">
                <div>
                    <div class="text-xs font-semibold text-slate-300 mb-2 flex items-center justify-between">
                        <span>📦 대기 중인 원격 커밋 내역</span>
                        <span class="text-[10px] text-slate-500 font-mono">origin tracking</span>
                    </div>
                    <ul id="gitModalCommitsList" class="space-y-1.5 max-h-48 overflow-y-auto p-1 bg-slate-950/60 rounded-xl border border-slate-800">
                        <!-- Populated dynamically via JS -->
                    </ul>
                </div>

                <div class="p-3.5 bg-slate-950/80 rounded-2xl border border-indigo-500/30">
                    <div class="text-xs font-semibold text-indigo-300 mb-1.5 flex items-center justify-between">
                        <span>🚀 업데이트 & 핫-재배포 명령어</span>
                        <button id="copyGitCmdBtn" onclick="copyGitPullCommand()" 
                                class="px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold shadow transition-all flex items-center gap-1 cursor-pointer">
                            <i class="fa-solid fa-copy"></i> 복사
                        </button>
                    </div>
                    <div class="p-2.5 bg-slate-900 rounded-xl border border-slate-800 font-mono text-xs text-emerald-400 select-all">
                        git pull && ./deploy.sh
                    </div>
                    <p class="text-[11px] text-slate-400 mt-2">
                        💡 터미널에서 위 명령어를 실행하면 최신 소스코드를 가져와 즉시 라이브 프록시에 무중단 핫-배포합니다.
                    </p>
                </div>
            </div>

            <div class="flex justify-end pt-4 mt-4 border-t border-slate-800">
                <button onclick="closeGitPullModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl border border-slate-700 transition-all cursor-pointer">
                    닫기
                </button>
            </div>
        </div>
    </div>

    <!-- Graph Node Inspector Modal (With Neuralizer Wipe Button) -->
    <div id="graphNodeModal" class="hidden fixed inset-0 z-[80] bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass-card max-w-2xl w-full p-6 rounded-3xl border border-purple-500/40 shadow-2xl relative bg-slate-900/95 max-h-[85vh] overflow-y-auto">
            <button onclick="closeGraphNodeModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-200 text-lg">
                <i class="fa-solid fa-xmark"></i>
            </button>
            <div class="flex items-center justify-between gap-3 mb-4 pr-8">
                <div class="flex items-center gap-3">
                    <span id="modalNodeBadge" class="px-3 py-1 bg-purple-500/20 text-purple-300 font-bold rounded-xl text-xs border border-purple-500/30">
                        GOLD
                    </span>
                    <div>
                        <h2 class="text-base font-bold text-slate-100 flex items-center gap-2">
                            🧠 지식 노드 상세 정보
                            <span id="modalNodeId" class="text-xs font-mono text-purple-300">#id</span>
                        </h2>
                        <p id="modalNodeMeta" class="text-xs text-slate-400 mt-0.5 font-mono">가중치: 1.0x | LOC: 0줄 | $0.0000</p>
                    </div>
                </div>
            </div>
            <div class="space-y-4 text-xs">
                <div class="p-4 bg-slate-950/80 rounded-2xl border border-slate-800">
                    <span class="text-xs font-bold text-sky-300">📌 문제 및 요구사항:</span>
                    <div id="modalNodeProblem" class="text-xs text-slate-200 mt-1 leading-relaxed whitespace-pre-wrap"></div>
                </div>
                <div class="p-4 bg-slate-950/80 rounded-2xl border border-slate-800">
                    <span class="text-xs font-bold text-emerald-300">💡 적용 해결책 및 LLM 응답:</span>
                    <div id="modalNodeSolution" class="text-xs text-slate-300 mt-1 font-mono leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto"></div>
                </div>
            </div>
            <div class="mt-5 pt-3 border-t border-slate-800 flex items-center justify-between">
                <!-- ⚡ Neuralizer Action Button -->
                <button id="modalNeuralizeBtn" onclick="onModalNeuralizeClick()" 
                        class="px-3.5 py-2 bg-rose-950/60 hover:bg-rose-900 border border-rose-500/50 text-rose-300 text-xs font-bold rounded-xl shadow-lg transition-all flex items-center gap-2 cursor-pointer">
                    <i class="fa-solid fa-bolt-lightning text-amber-400"></i>
                    <span>⚡ Neuralizer (기억 소각)</span>
                </button>
                <div class="flex items-center gap-2">
                    <button onclick="closeGraphNodeModal()" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl cursor-pointer">
                        닫기
                    </button>
                </div>
            </div>
        </div>
    </div>

    <!-- Healing Factor Comparison Modal -->
    <div id="healingModal" class="hidden fixed inset-0 z-[70] bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
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

    <!-- Downscaling Savings Info Modal -->
    <div id="savingsInfoModal" class="hidden fixed inset-0 z-[70] bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass-card max-w-2xl w-full p-6 rounded-3xl border border-emerald-500/40 shadow-2xl relative bg-slate-900/95">
            <button onclick="closeSavingsInfoModal()" class="absolute top-4 right-4 text-slate-400 hover:text-slate-200 text-lg">
                <i class="fa-solid fa-xmark"></i>
            </button>
            
            <div class="flex items-center gap-3 mb-5">
                <span class="p-3 bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 rounded-2xl text-xl">
                    <i class="fa-solid fa-calculator"></i>
                </span>
                <div>
                    <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
                        다운스케일링 누적 절감액 산출 기준 및 수식
                    </h2>
                    <p class="text-xs text-slate-400">하네스 스마트 라우팅을 통한 실질적 크레딧 방어 성과 (ROI)</p>
                </div>
            </div>

            <div class="space-y-4 text-xs text-slate-300 mb-6">
                <div class="p-4 bg-slate-800/80 rounded-2xl border border-slate-700 space-y-2">
                    <div class="font-bold text-emerald-400 text-sm flex items-center gap-1.5">
                        <i class="fa-solid fa-bullseye"></i> 비교 모델 기준 (Baseline vs Optimized)
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                        <div class="p-3 bg-slate-900/90 rounded-xl border border-rose-500/30">
                            <span class="text-rose-400 font-bold">📌 기준 기본 모델 (Baseline)</span>
                            <p class="text-slate-400 mt-1 font-mono text-[11px]">gpt-5.6-terra:medium</p>
                            <p class="text-slate-400 mt-0.5 text-[11px] leading-relaxed">하네스 미적용 시 모든 단순 작업 및 툴 루프까지 100% 투입되는 고비용 모델 (평균 턴당 ~$0.12 소모)</p>
                        </div>
                        <div class="p-3 bg-slate-900/90 rounded-xl border border-emerald-500/30">
                            <span class="text-emerald-400 font-bold">🛡️ 최적화 다운스케일 (Optimized)</span>
                            <p class="text-slate-300 mt-1 font-mono text-[11px]">gpt-5.6-luna (BRONZE / SILVER)</p>
                            <p class="text-slate-400 mt-0.5 text-[11px] leading-relaxed">난이도 분류기가 단순 작업(오타, 파일 조회, 사소한 수정)을 감지하여 초경량 모델로 자동 전환</p>
                        </div>
                    </div>
                </div>

                <div class="p-4 bg-slate-800/80 rounded-2xl border border-slate-700 space-y-2">
                    <div class="font-bold text-sky-400 text-sm flex items-center gap-1.5">
                        <i class="fa-solid fa-square-root-variable"></i> 정량적 산출 공식 (Mathematical Formula)
                    </div>
                    <div class="p-3 bg-slate-950 font-mono text-emerald-300 rounded-xl border border-slate-700 text-[11px] leading-relaxed space-y-1">
                        <div>1. 가상 소모 비용 (하네스 미적용 시) = ∑(LUNA 턴 토큰 × TERRA 모델 단가 [$2.50/M in, $10.00/M out])</div>
                        <div>2. 실제 소모 비용 (하네스 적용 시)   = ∑(LUNA 경량 모델 턴 실소모 비용 [$1.00/M in, $3.00/M out])</div>
                        <div>3. 순수 절감액 (Saved USD)          = 가상 소모 비용 - 실제 소모 비용</div>
                        <div>4. 아낀 크레딧 (Saved Credits)      = 순수 절감액 / $0.20 (1 Credit = $0.20 USD)</div>
                    </div>
                </div>

                <div class="p-3 bg-indigo-950/30 rounded-xl border border-indigo-500/30 text-[11px] text-indigo-300 flex items-start gap-2">
                    <i class="fa-solid fa-lightbulb text-indigo-400 mt-0.5"></i>
                    <span>에이전트는 대화가 길어질수록 5~10만 토큰의 컨텍스트를 매 턴마다 반복 전송합니다. 후반 단순 작업 스텝을 경량 모델로 다운스케일링함으로써 회사 월간 크레딧 한도를 안전하게 방어합니다.</span>
                </div>
            </div>

            <div class="flex justify-end pt-3 border-t border-slate-800">
                <button onclick="closeSavingsInfoModal()" class="px-5 py-2 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold rounded-xl shadow-lg transition-all">
                    확인 완료
                </button>
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
            
            // Map session stats
            const sessionMap = {{}};
            allRecords.forEach(r => {{
                const sid = r.session_id;
                if (!sid || sid === 'N/A') return;
                if (!sessionMap[sid]) {{
                    sessionMap[sid] = {{
                        id: sid,
                        lastTime: r.timestamp || '',
                        count: 0,
                        credit: 0
                    }};
                }}
                sessionMap[sid].count += 1;
                const cr = (r.real_credit !== undefined && r.real_credit !== null && !isNaN(r.real_credit)) ? parseFloat(r.real_credit) : ((r.cost || 0) / 0.20);
                sessionMap[sid].credit += cr;
                if (r.timestamp && (!sessionMap[sid].lastTime || r.timestamp > sessionMap[sid].lastTime)) {{
                    sessionMap[sid].lastTime = r.timestamp;
                }}
            }});

            // Sort by most recent activity descending
            const sortedSessions = Object.values(sessionMap).sort((a, b) => {{
                return (b.lastTime || '').localeCompare(a.lastTime || '');
            }});

            let html = '<option value="ALL">🌐 전체 세션 (All Sessions)</option>';
            if (sortedSessions.length > 0) {{
                html += '<option value="LATEST">🔥 최신 활성 세션 (Current Active)</option>';
            }}

            sortedSessions.forEach((s, idx) => {{
                const sShort = s.id.length > 8 ? s.id.substring(0, 8) : s.id;
                const timeLabel = s.lastTime ? s.lastTime.substring(5, 16) : 'N/A'; // MM-DD HH:mm
                const isLatest = idx === 0;
                const prefix = isLatest ? '🔥 [최신] ' : '';
                const label = `${{prefix}}${{timeLabel}} | ${{sShort}} (${{s.count}}턴 · ${{s.credit.toFixed(2)}} Cr)`;
                const isSelected = (s.id === currentVal);
                html += `<option value="${{s.id}}" ${{isSelected ? 'selected' : ''}}>${{label}}</option>`;
            }});

            select.innerHTML = html;
            if (currentVal === 'ALL' || currentVal === 'LATEST') select.value = currentVal;
        }}

        function selectSessionFilter(sid) {{
            const select = document.getElementById('sessionSelect');
            if (select) {{
                select.value = sid;
                onFilterChange();
                window.scrollTo({{ top: 0, behavior: 'smooth' }});
            }}
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

        function openSavingsInfoModal() {{
            document.getElementById('savingsInfoModal').classList.remove('hidden');
        }}

        function closeSavingsInfoModal() {{
            document.getElementById('savingsInfoModal').classList.add('hidden');
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

        let currentMetricFocus = 'dual'; // 'dual' | 'credit' | 'token' | 'cumulative'
        let currentSessionTurnFilter = 'merged'; // 'merged' | 'model' | 'all'

        function setChartMetricFocus(mode) {{
            currentMetricFocus = mode;
            const focusMap = {{
                'dual': 'chartFocusDual',
                'credit': 'chartFocusCredit',
                'token': 'chartFocusToken',
                'cumulative': 'chartFocusCumulative'
            }};
            Object.keys(focusMap).forEach(key => {{
                const btn = document.getElementById(focusMap[key]);
                if (btn) {{
                    if (key === mode) {{
                        btn.className = 'px-2.5 py-1 rounded-lg font-bold transition-all bg-indigo-600 text-white shadow-sm cursor-pointer';
                    }} else {{
                        btn.className = 'px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer';
                    }}
                }}
            }});
            const currentMonth = document.getElementById('monthSelect') ? document.getElementById('monthSelect').value : 'ALL';
            const currentSession = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
            renderDashboard(currentMonth, currentSession);
        }}

        function setSessionTurnFilter(mode) {{
            currentSessionTurnFilter = mode;
            const turnFilterMap = {{
                'merged': 'turnFilterMerged',
                'model': 'turnFilterModel',
                'all': 'turnFilterAll'
            }};
            Object.keys(turnFilterMap).forEach(key => {{
                const btn = document.getElementById(turnFilterMap[key]);
                if (btn) {{
                    if (key === mode) {{
                        btn.className = 'px-2.5 py-1 rounded-lg font-bold transition-all bg-purple-600 text-white shadow-sm cursor-pointer';
                    }} else {{
                        btn.className = 'px-2.5 py-1 rounded-lg font-semibold text-slate-400 hover:text-slate-200 transition-all cursor-pointer';
                    }}
                }}
            }});
            const currentMonth = document.getElementById('monthSelect') ? document.getElementById('monthSelect').value : 'ALL';
            const currentSession = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
            renderDashboard(currentMonth, currentSession);
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
                if (targetSession === 'LATEST') {{
                    let latestSid = null;
                    let maxTime = '';
                    allRecords.forEach(r => {{
                        if (r.session_id && r.session_id !== 'N/A' && r.timestamp && r.timestamp > maxTime) {{
                            maxTime = r.timestamp;
                            latestSid = r.session_id;
                        }}
                    }});
                    if (latestSid) {{
                        filteredRecords = filteredRecords.filter(r => r.session_id === latestSid);
                    }}
                }} else {{
                    filteredRecords = filteredRecords.filter(r => r.session_id === targetSession || r.session_id.includes(targetSession));
                }}
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
            let lunaCost = 0;
            let lunaInTok = 0;
            let lunaOutTok = 0;
            let totalRealCredits = 0;
            let hasRealCredit = false;

            filteredRecords.forEach(r => {{
                if (r.real_credit !== undefined && r.real_credit !== null) {{
                    totalRealCredits += r.real_credit;
                    hasRealCredit = true;
                }}
                if (r.decision === 'CLASSIFIER') {{
                    clfCost += r.cost;
                }} else {{
                    mainCost += r.cost;
                    if (r.decision.includes('BRONZE') || r.decision.includes('SILVER') || r.decision.includes('LUNA')) {{
                        lunaCost += r.cost;
                        lunaInTok += (r.input_tokens || 0);
                        lunaOutTok += (r.output_tokens || 0);
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
            const simTerraCost = (lunaInTok / 1000000.0) * 2.50 + (lunaOutTok / 1000000.0) * 10.00;
            const savedUsd = Math.max(0, simTerraCost - lunaCost);
            const savedCredits = savedUsd / 0.20;

            let displayCredits = (hasRealCredit && totalRealCredits > 0) ? totalRealCredits : totalCredits;
            let creditDisplayHtml = displayCredits.toFixed(2) + ' <span class="text-sm font-normal text-slate-400">Cr</span>';
            let breakdownHtml = `<span class="text-indigo-300 font-bold">🤖 모델: ${{mainCredits.toFixed(2)}} Cr</span> <span class="text-slate-500">|</span> <span class="text-amber-300 font-bold">🔍 분류기: ${{clfCredits.toFixed(2)}} Cr</span>`;
            if (hasRealCredit && totalRealCredits > 0) {{
                const cacheDiscountPct = totalCredits > 0 ? Math.max(0, Math.round((1 - (totalRealCredits / totalCredits)) * 100)) : 0;
                breakdownHtml = `<span class="text-emerald-300 font-bold" title="OpenAI 엔터프라이즈 계정 실제 차감">💳 계정 실차감</span> <span class="text-slate-500">|</span> <span class="text-slate-400" title="캐시 미적용 정가 기준">정가: ${{totalCredits.toFixed(2)}} Cr (${{cacheDiscountPct}}% 캐시할인)</span>`;
            }}

            document.getElementById('kpiCredits').innerHTML = creditDisplayHtml;
            document.getElementById('kpiCreditBreakdown').innerHTML = breakdownHtml;
            document.getElementById('kpiCost').innerText = '$' + totalCost.toFixed(4);
            document.getElementById('kpiRequests').innerText = '총 ' + filteredRecords.length.toLocaleString() + '회 성사 (모델: $' + mainCost.toFixed(4) + ' / 분류기: $' + clfCost.toFixed(4) + ')';
            document.getElementById('kpiTokens').innerText = totalTok.toLocaleString();
            document.getElementById('kpiInTokens').innerText = 'Input: ' + totalIn.toLocaleString();
            document.getElementById('kpiSessions').innerHTML = sessions.toLocaleString() + ' <span class="text-sm font-normal text-slate-400">sessions</span>';
            document.getElementById('kpiSavingsUsd').innerText = '$' + savedUsd.toFixed(2);
            document.getElementById('kpiSavingsCredits').innerText = '약 ' + savedCredits.toFixed(1) + ' Cr 크레딧 아낌';

            // 세션 선택 여부 및 인터랙티브 툴바 가시성 제어
            const isSessionSelected = targetSession && targetSession !== 'ALL';
            const sessionTurnFilterGroup = document.getElementById('sessionTurnFilterGroup');
            if (sessionTurnFilterGroup) {{
                if (isSessionSelected) {{
                    sessionTurnFilterGroup.classList.remove('hidden');
                }} else {{
                    sessionTurnFilterGroup.classList.add('hidden');
                }}
            }}

            function getRecordCredits(rec) {{
                if (!rec) return 0.0;
                if (rec.real_credit !== undefined && rec.real_credit !== null) {{
                    return parseFloat(rec.real_credit);
                }}
                return parseFloat((rec.cost / 0.20).toFixed(4));
            }}

            let chartLabels = [];
            let chartDatasets = [];
            let chartTurnMeta = [];
            let needsDualAxis = (currentMetricFocus === 'dual' || currentMetricFocus === 'cumulative');

            const isDark = document.documentElement.classList.contains('dark') || (!document.documentElement.classList.contains('light') && window.matchMedia('(prefers-color-scheme: dark)').matches);
            const gridColor = isDark ? 'rgba(51, 65, 85, 0.3)' : 'rgba(226, 232, 240, 0.8)';
            const tickColor = isDark ? '#94a3b8' : '#64748b';

            if (isSessionSelected) {{
                const titleTextEl = document.getElementById('timelineChartTitleText');
                const subTextEl = document.getElementById('timelineChartSubText');
                const iconEl = document.getElementById('timelineChartIcon');
                if (titleTextEl) titleTextEl.innerText = '세션 턴별 정밀 실차감 추이 (Session Turn Timeline)';
                if (subTextEl) subTextEl.innerText = `세션 ID: ${{targetSession.length > 18 ? targetSession.substring(0, 18) + '...' : targetSession}}`;
                if (iconEl) iconEl.className = 'fa-solid fa-clock-rotate-left text-emerald-400';

                // 세션 내 시간순 정렬
                const sessionRecords = [...filteredRecords].sort((a, b) => {{
                    const tA = a.timestamp || a.date || '';
                    const tB = b.timestamp || b.date || '';
                    return tA.localeCompare(tB);
                }});

                // 턴별 프롬프트 실시간 타임라인 테이블 렌더링
                const sessionTurnsSection = document.getElementById('sessionTurnsSection');
                const sessionTurnsBadge = document.getElementById('sessionTurnsBadge');
                const sessionTurnsSid = document.getElementById('sessionTurnsSid');
                const sessionTurnsTableBody = document.getElementById('sessionTurnsTableBody');
                if (sessionTurnsSection) sessionTurnsSection.classList.remove('hidden');
                if (sessionTurnsBadge) sessionTurnsBadge.innerText = `${{sessionRecords.length}} 턴`;
                if (sessionTurnsSid) sessionTurnsSid.innerText = targetSession;
                if (sessionTurnsTableBody) {{
                    let turnsHtml = '';
                    sessionRecords.forEach((r, idx) => {{
                        const credits = getRecordCredits(r).toFixed(2);
                        const timeStr = r.timestamp || r.date || 'N/A';
                        const safePrompt = (r.prompt || '(연속 서브스텝 / 툴 액션)').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
                        
                        let badgeClass = 'bg-slate-800 text-slate-300 border-slate-600/40';
                        if (r.decision.includes('BRONZE')) {{
                            badgeClass = 'bg-amber-900/30 text-amber-300 border-amber-600/40';
                        }} else if (r.decision.includes('SILVER')) {{
                            badgeClass = 'bg-slate-700/40 text-slate-200 border-slate-400/40';
                        }} else if (r.decision.includes('GOLD')) {{
                            badgeClass = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                        }} else if (r.decision.includes('PLATINUM')) {{
                            badgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
                        }} else if (r.decision.includes('DIAMOND')) {{
                            badgeClass = 'bg-blue-500/20 text-blue-300 border-blue-400/40';
                        }} else if (r.decision.includes('CHALLENGER') || r.decision.includes('SOL')) {{
                            badgeClass = 'bg-rose-500/20 text-rose-300 border-rose-500/40 font-extrabold animate-pulse';
                        }} else if (r.decision.includes('CLASSIFIER')) {{
                            badgeClass = 'bg-purple-950/40 text-purple-300 border-purple-600/40 font-mono';
                        }}

                        turnsHtml += `
                        <tr class="hover:bg-slate-800/60 transition-colors border-b border-slate-800/80">
                            <td class="px-3 py-2.5 font-mono text-purple-300 font-bold">Turn ${{idx + 1}}</td>
                            <td class="px-3 py-2.5 font-mono text-slate-400 whitespace-nowrap">${{timeStr}}</td>
                            <td class="px-3 py-2.5 text-center">
                                <span class="px-2 py-0.5 text-xs font-semibold rounded-full border ${{badgeClass}}">
                                    ${{r.decision}}
                                </span>
                            </td>
                            <td class="px-3 py-2.5 text-slate-200 font-medium max-w-md truncate" title="${{safePrompt}}">${{safePrompt}}</td>
                            <td class="px-3 py-2.5 text-right font-mono text-slate-400 whitespace-nowrap">${{r.input_tokens.toLocaleString()}} / ${{r.output_tokens.toLocaleString()}}</td>
                            <td class="px-3 py-2.5 text-right font-mono text-sky-400 font-semibold whitespace-nowrap">${{r.total_tokens.toLocaleString()}}</td>
                            <td class="px-3 py-2.5 text-right font-mono text-emerald-400 font-bold whitespace-nowrap">${{credits}} Cr</td>
                        </tr>
                        `;
                    }});
                    sessionTurnsTableBody.innerHTML = turnsHtml;
                }}

                // [지능형 턴 구성] 1턴 통합(페어링) vs 모델만 vs 원시 전체 (실차감 크레딧 기준)
                let processedTurns = [];
                if (currentSessionTurnFilter === 'merged') {{
                    let pendingClassifier = null;
                    sessionRecords.forEach(r => {{
                        if (r.decision.includes('CLASSIFIER')) {{
                            pendingClassifier = r;
                        }} else {{
                            const timeStr = (r.timestamp && r.timestamp.length >= 19) ? r.timestamp.substring(11, 19) : (r.date || '');
                            const mainCredits = getRecordCredits(r);
                            const clfCredits = pendingClassifier ? getRecordCredits(pendingClassifier) : 0.0;
                            const totalTurnCredits = mainCredits + clfCredits;
                            const mainIn = r.input_tokens || 0;
                            const mainOut = r.output_tokens || 0;
                            const clfIn = pendingClassifier ? (pendingClassifier.input_tokens || 0) : 0;
                            const clfOut = pendingClassifier ? (pendingClassifier.output_tokens || 0) : 0;
                            const totalIn = mainIn + clfIn;
                            const totalOut = mainOut + clfOut;
                            const totalTok = totalIn + totalOut;

                            processedTurns.push({{
                                turnNumber: processedTurns.length + 1,
                                timeStr: timeStr,
                                fullTime: r.timestamp || 'N/A',
                                decision: r.decision,
                                model: r.model || 'N/A',
                                prompt: r.prompt || '(연속 서브스텝 / 툴 액션)',
                                mainCredits: parseFloat(mainCredits.toFixed(4)),
                                clfCredits: parseFloat(clfCredits.toFixed(4)),
                                totalCredits: parseFloat(totalTurnCredits.toFixed(4)),
                                inTok: totalIn,
                                outTok: totalOut,
                                tokens: totalTok,
                                isMerged: !!pendingClassifier
                            }});
                            pendingClassifier = null;
                        }}
                    }});
                    // Note: In 'merged' mode, any in-flight pendingClassifier waiting for the main model response
                    // is not pushed as an isolated incomplete turn, completely preventing the rightmost token plunge.
                }} else if (currentSessionTurnFilter === 'model') {{
                    sessionRecords.filter(r => !r.decision.includes('CLASSIFIER')).forEach((r, idx) => {{
                        const timeStr = (r.timestamp && r.timestamp.length >= 19) ? r.timestamp.substring(11, 19) : (r.date || '');
                        const credits = getRecordCredits(r);
                        processedTurns.push({{
                            turnNumber: idx + 1,
                            timeStr: timeStr,
                            fullTime: r.timestamp || 'N/A',
                            decision: r.decision,
                            model: r.model || 'N/A',
                            prompt: r.prompt || '(연속 서브스텝 / 툴 액션)',
                            mainCredits: parseFloat(credits.toFixed(4)),
                            clfCredits: 0.0,
                            totalCredits: parseFloat(credits.toFixed(4)),
                            inTok: r.input_tokens || 0,
                            outTok: r.output_tokens || 0,
                            tokens: r.total_tokens || 0,
                            isMerged: false
                        }});
                    }});
                }} else {{
                    // 원시 전체 (all)
                    sessionRecords.forEach((r, idx) => {{
                        const timeStr = (r.timestamp && r.timestamp.length >= 19) ? r.timestamp.substring(11, 19) : (r.date || '');
                        const credits = getRecordCredits(r);
                        processedTurns.push({{
                            turnNumber: idx + 1,
                            timeStr: timeStr,
                            fullTime: r.timestamp || 'N/A',
                            decision: r.decision,
                            model: r.model || 'N/A',
                            prompt: r.prompt || '(연속 서브스텝 / 툴 액션)',
                            mainCredits: r.decision.includes('CLASSIFIER') ? 0.0 : parseFloat(credits.toFixed(4)),
                            clfCredits: r.decision.includes('CLASSIFIER') ? parseFloat(credits.toFixed(4)) : 0.0,
                            totalCredits: parseFloat(credits.toFixed(4)),
                            inTok: r.input_tokens || 0,
                            outTok: r.output_tokens || 0,
                            tokens: r.total_tokens || 0,
                            isMerged: false
                        }});
                    }});
                }}

                // 누적 데이터 산출
                let cumCredit = 0;
                let cumToken = 0;
                processedTurns.forEach(pt => {{
                    cumCredit += pt.totalCredits;
                    cumToken += pt.tokens;
                    pt.cumCredit = parseFloat(cumCredit.toFixed(2));
                    pt.cumToken = cumToken;

                    chartLabels.push(`Turn ${{pt.turnNumber}} [${{pt.timeStr}}]`);
                    chartTurnMeta.push(pt);
                }});

                // currentMetricFocus 에 따라 인터랙티브 데이터셋 구성 (실차감 기준)
                if (currentMetricFocus === 'dual') {{
                    chartDatasets = [
                        {{
                            label: '계정 실차감 크레딧 (Cr)',
                            data: processedTurns.map(p => p.totalCredits),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.12)',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.25,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '소모 토큰 (Tokens)',
                            data: processedTurns.map(p => p.tokens),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.05)',
                            borderWidth: 2,
                            borderDash: [4, 4],
                            fill: false,
                            tension: 0.25,
                            yAxisID: 'y1'
                        }}
                    ];
                }} else if (currentMetricFocus === 'credit') {{
                    chartDatasets = [
                        {{
                            label: '🤖 메인 에이전트 실차감 (Cr)',
                            data: processedTurns.map(p => p.mainCredits),
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.15)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.25,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '🔍 분류기 실차감 (Cr)',
                            data: processedTurns.map(p => p.clfCredits),
                            borderColor: '#f59e0b',
                            backgroundColor: 'rgba(245, 158, 11, 0.08)',
                            borderWidth: 1.5,
                            borderDash: [3, 3],
                            fill: false,
                            tension: 0.2,
                            yAxisID: 'y'
                        }}
                    ];
                }} else if (currentMetricFocus === 'token') {{
                    chartDatasets = [
                        {{
                            label: '📥 Input 토큰',
                            data: processedTurns.map(p => p.inTok),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.12)',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.25,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '📤 Output 토큰',
                            data: processedTurns.map(p => p.outTok),
                            borderColor: '#c084fc',
                            backgroundColor: 'rgba(192, 132, 252, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.25,
                            yAxisID: 'y'
                        }}
                    ];
                }} else if (currentMetricFocus === 'cumulative') {{
                    chartDatasets = [
                        {{
                            label: '📈 누적 실차감 크레딧 (Cum Cr)',
                            data: processedTurns.map(p => p.cumCredit),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.2)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.35,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '📊 누적 토큰 (Cum Tokens)',
                            data: processedTurns.map(p => p.cumToken),
                            borderColor: '#60a5fa',
                            backgroundColor: 'transparent',
                            borderWidth: 2,
                            borderDash: [4, 4],
                            fill: false,
                            tension: 0.35,
                            yAxisID: 'y1'
                        }}
                    ];
                }}
            }} else {{
                // 전체 일자별 뷰
                const sessionTurnsSection = document.getElementById('sessionTurnsSection');
                if (sessionTurnsSection) sessionTurnsSection.classList.add('hidden');
                const titleTextEl = document.getElementById('timelineChartTitleText');
                const subTextEl = document.getElementById('timelineChartSubText');
                const iconEl = document.getElementById('timelineChartIcon');
                if (titleTextEl) titleTextEl.innerText = '선택 기간 일자별 추이 (Daily Trend)';
                if (subTextEl) subTextEl.innerText = 'Kibana Live Timeline';
                if (iconEl) iconEl.className = 'fa-solid fa-chart-area text-sky-400';

                const dailyMap = {{}};
                filteredRecords.forEach(r => {{
                    if (!dailyMap[r.date]) dailyMap[r.date] = {{ cost: 0, tokens: 0, in_tok: 0, out_tok: 0, credits: 0 }};
                    dailyMap[r.date].cost += r.cost;
                    dailyMap[r.date].tokens += r.total_tokens;
                    dailyMap[r.date].in_tok += r.input_tokens;
                    dailyMap[r.date].out_tok += r.output_tokens;
                    dailyMap[r.date].credits += getRecordCredits(r);
                }});

                chartLabels = Object.keys(dailyMap).sort();
                let cumC = 0;
                let cumT = 0;
                const dailyPoints = chartLabels.map(d => {{
                    const cr = parseFloat(dailyMap[d].credits.toFixed(2));
                    const tok = dailyMap[d].tokens;
                    cumC += cr;
                    cumT += tok;
                    return {{
                        date: d,
                        credits: cr,
                        tokens: tok,
                        in_tok: dailyMap[d].in_tok,
                        out_tok: dailyMap[d].out_tok,
                        cumCredits: parseFloat(cumC.toFixed(2)),
                        cumTokens: cumT
                    }};
                }});

                if (currentMetricFocus === 'dual') {{
                    chartDatasets = [
                        {{
                            label: '일별 실차감 크레딧 (Cr)',
                            data: dailyPoints.map(p => p.credits),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.12)',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '일별 토큰 (Tokens)',
                            data: dailyPoints.map(p => p.tokens),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.05)',
                            borderWidth: 2,
                            borderDash: [4, 4],
                            fill: false,
                            tension: 0.3,
                            yAxisID: 'y1'
                        }}
                    ];
                }} else if (currentMetricFocus === 'credit') {{
                    chartDatasets = [
                        {{
                            label: '💳 일별 실차감 크레딧 (Cr)',
                            data: dailyPoints.map(p => p.credits),
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.15)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }}
                    ];
                }} else if (currentMetricFocus === 'token') {{
                    chartDatasets = [
                        {{
                            label: '📥 Input 토큰',
                            data: dailyPoints.map(p => p.in_tok),
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.12)',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '📤 Output 토큰',
                            data: dailyPoints.map(p => p.out_tok),
                            borderColor: '#c084fc',
                            backgroundColor: 'rgba(192, 132, 252, 0.1)',
                            borderWidth: 2,
                            fill: true,
                            tension: 0.3,
                            yAxisID: 'y'
                        }}
                    ];
                }} else if (currentMetricFocus === 'cumulative') {{
                    chartDatasets = [
                        {{
                            label: '📈 누적 실차감 크레딧 (Cum Cr)',
                            data: dailyPoints.map(p => p.cumCredits),
                            borderColor: '#34d399',
                            backgroundColor: 'rgba(52, 211, 153, 0.2)',
                            borderWidth: 3,
                            fill: true,
                            tension: 0.35,
                            yAxisID: 'y'
                        }},
                        {{
                            label: '📊 누적 토큰 (Cum Tokens)',
                            data: dailyPoints.map(p => p.cumTokens),
                            borderColor: '#60a5fa',
                            backgroundColor: 'transparent',
                            borderWidth: 2,
                            borderDash: [4, 4],
                            fill: false,
                            tension: 0.35,
                            yAxisID: 'y1'
                        }}
                    ];
                }}
            }}

            window.currentChartTurnMeta = chartTurnMeta;
            window.currentIsSessionSelected = isSessionSelected;

            if (dailyChart) {{
                dailyChart.data.labels = chartLabels;
                dailyChart.data.datasets = chartDatasets;
                dailyChart.options.scales.y1.display = needsDualAxis;
                dailyChart.update('none');
            }} else {{
                dailyChart = new Chart(document.getElementById('dailyTrendChart'), {{
                    type: 'line',
                    data: {{
                        labels: chartLabels,
                        datasets: chartDatasets
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {{
                            mode: 'index',
                            intersect: false
                        }},
                        plugins: {{
                            legend: {{ 
                                labels: {{ color: tickColor, font: {{ family: 'Inter', size: 11, weight: 'bold' }} }},
                                onHover: function(e, legendItem, legend) {{
                                    const ci = legend.chart;
                                    ci.data.datasets.forEach((dataset, i) => {{
                                        dataset._origBorderColor = dataset._origBorderColor || dataset.borderColor;
                                        dataset._origBackgroundColor = dataset._origBackgroundColor || dataset.backgroundColor;
                                        dataset._origBorderWidth = dataset._origBorderWidth || dataset.borderWidth;
                                        if (i === legendItem.datasetIndex) {{
                                            dataset.borderWidth = dataset._origBorderWidth + 1;
                                        }} else {{
                                            dataset.borderColor = (dataset._origBorderColor && dataset._origBorderColor.startsWith('rgba')) ? (dataset._origBorderColor.split(',').slice(0, 3).join(',') + ', 0.15)') : 'rgba(148, 163, 184, 0.15)';
                                            dataset.backgroundColor = 'transparent';
                                        }}
                                    }});
                                    ci.update('none');
                                }},
                                onLeave: function(e, legendItem, legend) {{
                                    const ci = legend.chart;
                                    ci.data.datasets.forEach((dataset) => {{
                                        if (dataset._origBorderColor) dataset.borderColor = dataset._origBorderColor;
                                        if (dataset._origBackgroundColor) dataset.backgroundColor = dataset._origBackgroundColor;
                                        if (dataset._origBorderWidth) dataset.borderWidth = dataset._origBorderWidth;
                                    }});
                                    ci.update('none');
                                }}
                            }},
                            tooltip: {{
                                backgroundColor: isDark ? 'rgba(15, 23, 42, 0.96)' : 'rgba(255, 255, 255, 0.98)',
                                titleColor: isDark ? '#38bdf8' : '#0284c7',
                                bodyColor: isDark ? '#e2e8f0' : '#1e293b',
                                borderColor: isDark ? 'rgba(56, 189, 248, 0.3)' : 'rgba(203, 213, 225, 0.9)',
                                borderWidth: 1,
                                padding: 12,
                                boxPadding: 6,
                                usePointStyle: true,
                                callbacks: {{
                                    title: function(items) {{
                                        if (!items || items.length === 0) return '';
                                        const idx = items[0].dataIndex;
                                        const meta = window.currentChartTurnMeta;
                                        if (window.currentIsSessionSelected && meta && meta[idx]) {{
                                            const m = meta[idx];
                                            return `🎯 Turn ${{m.turnNumber}} [${{m.timeStr || m.fullTime}}]`;
                                        }}
                                        return items[0].label;
                                    }},
                                    afterTitle: function(items) {{
                                        if (!items || items.length === 0) return '';
                                        const idx = items[0].dataIndex;
                                        const meta = window.currentChartTurnMeta;
                                        if (window.currentIsSessionSelected && meta && meta[idx] && meta[idx].decision) {{
                                            const m = meta[idx];
                                            return `🤖 라우팅: [${{m.decision}}] (${{m.model}})`;
                                        }}
                                        return '';
                                    }},
                                    afterBody: function(items) {{
                                        if (!items || items.length === 0) return '';
                                        const idx = items[0].dataIndex;
                                        const meta = window.currentChartTurnMeta;
                                        if (window.currentIsSessionSelected && meta && meta[idx]) {{
                                            const m = meta[idx];
                                            let extra = '';
                                            if (m.isMerged) {{
                                                extra += `\n💳 턴 실차감: 모델 ${{m.mainCredits}} Cr + 분류기 ${{m.clfCredits}} Cr`;
                                            }}
                                            if (m.inTok !== undefined) {{
                                                extra += `\n📦 토큰 세부: In ${{m.inTok.toLocaleString()}} / Out ${{m.outTok.toLocaleString()}}`;
                                            }}
                                            if (m.prompt) {{
                                                const shortPrompt = m.prompt.length > 70 ? m.prompt.substring(0, 70) + '...' : m.prompt;
                                                extra += `\n💬 프롬프트:\n"${{shortPrompt}}"`;
                                            }}
                                            return extra;
                                        }}
                                        return '';
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{ grid: {{ color: gridColor }}, ticks: {{ color: tickColor }} }},
                            y: {{ position: 'left', grid: {{ color: gridColor }}, ticks: {{ color: '#34d399' }} }},
                            y1: {{ display: needsDualAxis, position: 'right', grid: {{ drawOnChartArea: false }}, ticks: {{ color: '#38bdf8' }} }}
                        }}
                    }}
                }});
            }}

            const decMap = {{}};
            filteredRecords.forEach(r => {{
                if (!decMap[r.decision]) decMap[r.decision] = 0;
                decMap[r.decision] += getRecordCredits(r);
            }});

            const decLabels = Object.keys(decMap).sort((a,b) => decMap[b] - decMap[a]);
            const decCreditsData = decLabels.map(k => decMap[k].toFixed(2));

            if (decisionChart) {{
                decisionChart.data.labels = decLabels;
                decisionChart.data.datasets[0].data = decCreditsData;
                decisionChart.update('none');
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

            // 프롬프트 그룹화 및 세션 랭킹 수합 (CLASSIFIER 덮어쓰기 방지 및 턴수 중복 보정)
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
                // CLASSIFIER는 보조 분류 로그이므로 메인 모델 등급(BRONZE, SILVER, GOLD, PLATINUM 등)을 우선 적용
                if (r.decision !== 'CLASSIFIER' || promptMap[pKey].decision === 'CLASSIFIER') {{
                    promptMap[pKey].decision = r.decision;
                }}
                // 메인 턴 기준으로 요청 횟수 카운트
                if (r.decision !== 'CLASSIFIER') {{
                    promptMap[pKey].count += 1;
                }}
                promptMap[pKey].tokens += r.total_tokens;
                promptMap[pKey].cost += r.cost;
            }});

            // 순수 분류기만 발생한 경우 최소 1회 보정
            Object.values(promptMap).forEach(p => {{
                if (p.count === 0) p.count = 1;
            }});

            const allSortedPrompts = Object.values(promptMap).sort((a,b) => b.cost - a.cost);
            const totalPromptsCount = allSortedPrompts.length;

            const visiblePrompts = allSortedPrompts.slice(0, currentPromptLimit);
            let tableHtml = '';
            
            visiblePrompts.forEach((p, idx) => {{
                const credits = (p.cost / 0.20).toFixed(2);
                const sidFull = p.session_id || 'N/A';
                const sidShort = (sidFull !== 'N/A' && sidFull.length > 8) ? sidFull.substring(0, 8) : sidFull;
                
                let badgeClass = 'bg-slate-800 text-slate-300 border-slate-600/40';
                if (p.decision.includes('BRONZE')) {{
                    badgeClass = 'bg-amber-900/30 text-amber-300 border-amber-600/40';
                }} else if (p.decision.includes('SILVER')) {{
                    badgeClass = 'bg-slate-700/40 text-slate-200 border-slate-400/40';
                }} else if (p.decision.includes('GOLD')) {{
                    badgeClass = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                }} else if (p.decision.includes('PLATINUM')) {{
                    badgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
                }} else if (p.decision.includes('DIAMOND')) {{
                    badgeClass = 'bg-blue-500/20 text-blue-300 border-blue-400/40';
                }} else if (p.decision.includes('CHALLENGER') || p.decision.includes('SOL')) {{
                    badgeClass = 'bg-rose-500/20 text-rose-300 border-rose-500/40 font-extrabold animate-pulse';
                }} else if (p.decision.includes('CLASSIFIER')) {{
                    badgeClass = 'bg-purple-950/40 text-purple-300 border-purple-600/40 font-mono';
                }}

                const safePrompt = p.prompt.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

                tableHtml += `
                <tr class="hover:bg-slate-800/50 transition-colors border-b border-slate-800/80" data-session-id="${{sidFull}}" data-session-short="${{sidShort}}">
                    <td class="px-4 py-3 text-slate-400 font-mono text-sm font-bold">${{idx + 1}}</td>
                    <td class="px-4 py-3 font-mono text-xs"><button onclick="selectSessionFilter('${{sidFull}}')" class="text-sky-400 hover:text-sky-200 hover:underline cursor-pointer flex items-center gap-1 font-bold" title="${{sidFull}} 세션 필터 적용"><i class="fa-solid fa-filter text-[10px] opacity-70"></i>${{sidShort}}</button></td>
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

            const loadMoreBtn = document.getElementById('loadMoreBtn');
            const countInfo = document.getElementById('promptDisplayCountInfo');

            if (currentPromptLimit >= totalPromptsCount) {{
                loadMoreBtn.classList.add('hidden');
                countInfo.innerText = `전체 ${{totalPromptsCount.toLocaleString()}}개 표시 완료`;
            }} else {{
                loadMoreBtn.classList.remove('hidden');
                countInfo.innerText = `표시 중: Top ${{visiblePrompts.length.toLocaleString()}} / 전체 ${{totalPromptsCount.toLocaleString()}}개`;
            }}

            filterTable();
            // 🧠 생각나무 질의 뿌리 재구성 및 성단형 그래프 선택 세션 포커스 동기화
            focusSessionInGraph(targetSession);
            if (markmapInstance) {{
                initMarkmapTree();
            }}
        }}

        function onFilterChange() {{
            currentPromptLimit = 15;
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
                    if (input.includes('sess_') || input.length >= 6) {{
                        row.querySelector('td').innerText = visibleCount;
                    }}
                }}
            }});
        }}

        let currentMemories = {client_memories_json};
        let currentMemStats = {client_mem_stats_json};
        let currentGraphData = {client_graph_data_json};
        let currentTopEdges = {client_top_edges_json};
        let currentDashboardTab = 'usage';
        let currentModalViewMode = 'network';
        let markmapInstance = null;
        let markmapTransformer = null;
        let memoryNetwork = null;
        let isPhysicsEnabled = true;

        let currentTheme = localStorage.getItem('tb_theme') || 'dark';

        function formatGraphNodesForTheme(rawNodes, isDark) {{
            const fontColor = isDark ? '#f8fafc' : '#0f172a';
            const strokeColor = isDark ? '#020617' : '#ffffff';
            const strokeWidth = isDark ? 2 : 4;
            return (rawNodes || []).map(n => {{
                const nodeCopy = Object.assign({{}}, n);
                nodeCopy.font = {{
                    color: fontColor,
                    size: 11,
                    face: 'Pretendard, -apple-system, sans-serif',
                    strokeWidth: strokeWidth,
                    strokeColor: strokeColor
                }};
                return nodeCopy;
            }});
        }}

        function applyTheme(theme) {{
            currentTheme = theme;
            localStorage.setItem('tb_theme', theme);
            
            const isOsDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const isDark = (theme === 'dark') || (theme === 'system' && isOsDark);
            const htmlEl = document.documentElement;
            
            if (isDark) {{
                htmlEl.classList.add('dark');
                htmlEl.classList.remove('light');
            }} else {{
                htmlEl.classList.add('light');
                htmlEl.classList.remove('dark');
            }}

            const btnDark = document.getElementById('themeBtnDark');
            const btnLight = document.getElementById('themeBtnLight');
            const btnSystem = document.getElementById('themeBtnSystem');

            const activeBtnClass = 'px-2.5 py-1 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer bg-indigo-600 text-white shadow-md border border-indigo-400/40';
            const inactiveBtnClass = 'px-2.5 py-1 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200 border border-transparent';

            if (btnDark) btnDark.className = (theme === 'dark') ? activeBtnClass : inactiveBtnClass;
            if (btnLight) btnLight.className = (theme === 'light') ? activeBtnClass : inactiveBtnClass;
            if (btnSystem) {{
                btnSystem.className = (theme === 'system') ? activeBtnClass : inactiveBtnClass;
                btnSystem.title = `시스템 기본 (현재 OS: ${{isOsDark ? '어두운' : '밝은'}} 모드)`;
            }}

            // 테마 변경 시 생각나무(성단 네트워크 & 마인드맵) 뷰포트 즉시 리렌더링
            if (currentGraphData) {{
                initMemoryGraph(currentGraphData);
                initExpandedMemoryGraph(currentGraphData);
            }}
            if (markmapInstance) {{
                initMarkmapTree();
            }}
        }}

        function setTheme(theme) {{
            applyTheme(theme);
        }}

        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {{
            if (currentTheme === 'system') {{
                applyTheme('system');
            }}
        }});

        function switchDashboardTab(tab) {{
            currentDashboardTab = tab;
            const btnUsage = document.getElementById('tabBtnUsage');
            const btnMemory = document.getElementById('tabBtnMemory');
            const viewUsage = document.getElementById('usageView');
            const viewMemory = document.getElementById('memoryView');

            if (tab === 'usage') {{
                if (viewUsage) viewUsage.classList.remove('hidden');
                if (viewMemory) viewMemory.classList.add('hidden');
                if (btnUsage) btnUsage.className = 'px-5 py-2.5 rounded-xl text-xs font-bold transition-all duration-300 flex items-center gap-2.5 cursor-pointer bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg shadow-indigo-500/25 border border-indigo-400/30';
                if (btnMemory) btnMemory.className = 'px-5 py-2.5 rounded-xl text-xs font-semibold transition-all duration-300 flex items-center gap-2.5 cursor-pointer text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent';
            }} else {{
                if (viewUsage) viewUsage.classList.add('hidden');
                if (viewMemory) viewMemory.classList.remove('hidden');
                if (btnMemory) btnMemory.className = 'px-5 py-2.5 rounded-xl text-xs font-bold transition-all duration-300 flex items-center gap-2.5 cursor-pointer bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/25 border border-purple-400/30';
                if (btnUsage) btnUsage.className = 'px-5 py-2.5 rounded-xl text-xs font-semibold transition-all duration-300 flex items-center gap-2.5 cursor-pointer text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent';
                renderMemoryView(currentMemories, currentMemStats, currentGraphData, currentTopEdges);
                setTimeout(() => {{
                    initMemoryGraph(currentGraphData);
                    const curSid = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
                    focusSessionInGraph(curSid);
                }}, 50);
            }}
        }}

        let memoryMiniNetwork = null;
        let memoryExpandedNetwork = null;
        let miniVisNodes = null;
        let miniVisEdges = null;
        let modalVisNodes = null;
        let modalVisEdges = null;
        let isMiniPhysicsEnabled = true;
        let isModalPhysicsEnabled = true;
        let currentModalNodeId = null;

        function initMemoryGraph(graphData) {{
            const container = document.getElementById('memoryGraphCanvas');
            if (!container || !window.vis) return;

            const nodes = graphData.nodes || [];
            const edges = graphData.edges || [];

            if (nodes.length === 0) {{
                container.innerHTML = '<div class="text-slate-500 text-xs font-mono">기억 저장소에 연결된 노드가 아직 없습니다.</div>';
                return;
            }}

            const isDark = document.documentElement.classList.contains('dark') || (!document.documentElement.classList.contains('light') && window.matchMedia('(prefers-color-scheme: dark)').matches);
            const themedNodes = formatGraphNodesForTheme(nodes, isDark);

            miniVisNodes = new vis.DataSet(themedNodes);
            miniVisEdges = new vis.DataSet(edges);

            const nodeFontColor = isDark ? '#f8fafc' : '#0f172a';
            const nodeStrokeColor = isDark ? '#020617' : '#ffffff';
            const shadowColor = isDark ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.12)';
            const edgeColor = isDark ? 'rgba(168, 85, 247, 0.4)' : 'rgba(147, 51, 234, 0.6)';

            const data = {{ nodes: miniVisNodes, edges: miniVisEdges }};
            const options = {{
                nodes: {{
                    shape: 'dot',
                    scaling: {{ min: 14, max: 32, label: {{ min: 9, max: 12 }} }},
                    font: {{ 
                        color: nodeFontColor, 
                        face: 'Pretendard, -apple-system, sans-serif',
                        strokeWidth: isDark ? 2 : 4,
                        strokeColor: nodeStrokeColor
                    }},
                    borderWidth: 2,
                    shadow: {{ enabled: true, color: shadowColor, size: 6, x: 2, y: 2 }}
                }},
                edges: {{
                    arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
                    color: {{ color: edgeColor, highlight: '#ec4899', hover: '#a855f7' }},
                    smooth: {{ type: 'continuous' }}
                }},
                physics: {{
                    enabled: isMiniPhysicsEnabled,
                    stabilization: {{ iterations: 100 }},
                    barnesHut: {{ gravitationalConstant: -2400, springConstant: 0.04, springLength: 100 }}
                }},
                interaction: {{ hover: true, tooltipDelay: 80, zoomView: true, dragView: true }}
            }};

            if (memoryMiniNetwork) {{
                memoryMiniNetwork.destroy();
            }}

            memoryMiniNetwork = new vis.Network(container, data, options);

            memoryMiniNetwork.on('click', function(params) {{
                if (params.nodes.length > 0) {{
                    const nodeId = params.nodes[0];
                    const selectedNode = (currentGraphData.nodes || []).find(n => n.id === nodeId);
                    if (selectedNode) {{
                        openGraphNodeModal(selectedNode);
                        memoryMiniNetwork.focus(nodeId, {{ scale: 1.3, animation: {{ duration: 500, easingFunction: 'easeInOutQuad' }} }});
                    }}
                }}
            }});
        }}

        function initExpandedMemoryGraph(graphData) {{
            const container = document.getElementById('expandedMemoryGraphCanvas');
            if (!container || !window.vis) return;

            const nodes = (graphData && graphData.nodes) || (currentGraphData && currentGraphData.nodes) || [];
            const edges = (graphData && graphData.edges) || (currentGraphData && currentGraphData.edges) || [];

            if (nodes.length === 0) {{
                container.innerHTML = '<div class="text-slate-500 text-xs font-mono">기억 저장소에 연결된 노드가 아직 없습니다.</div>';
                return;
            }}

            const isDark = document.documentElement.classList.contains('dark') || (!document.documentElement.classList.contains('light') && window.matchMedia('(prefers-color-scheme: dark)').matches);
            const themedNodes = formatGraphNodesForTheme(nodes, isDark);

            modalVisNodes = new vis.DataSet(themedNodes);
            modalVisEdges = new vis.DataSet(edges);

            const nodeFontColor = isDark ? '#f8fafc' : '#0f172a';
            const nodeStrokeColor = isDark ? '#020617' : '#ffffff';
            const shadowColor = isDark ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.15)';
            const edgeColor = isDark ? 'rgba(168, 85, 247, 0.45)' : 'rgba(147, 51, 234, 0.65)';

            const data = {{ nodes: modalVisNodes, edges: modalVisEdges }};
            const options = {{
                nodes: {{
                    shape: 'dot',
                    scaling: {{ min: 18, max: 40, label: {{ min: 11, max: 14 }} }},
                    font: {{ 
                        color: nodeFontColor, 
                        face: 'Pretendard, -apple-system, sans-serif',
                        strokeWidth: isDark ? 2 : 4,
                        strokeColor: nodeStrokeColor
                    }},
                    borderWidth: 2,
                    shadow: {{ enabled: true, color: shadowColor, size: 8, x: 2, y: 2 }}
                }},
                edges: {{
                    arrows: {{ to: {{ enabled: true, scaleFactor: 0.7 }} }},
                    color: {{ color: edgeColor, highlight: '#ec4899', hover: '#a855f7' }},
                    smooth: {{ type: 'continuous' }}
                }},
                physics: {{
                    enabled: isModalPhysicsEnabled,
                    stabilization: {{ iterations: 120 }},
                    barnesHut: {{ gravitationalConstant: -3500, springConstant: 0.04, springLength: 140 }}
                }},
                interaction: {{ hover: true, tooltipDelay: 80, zoomView: true, dragView: true }}
            }};

            if (memoryExpandedNetwork) {{
                memoryExpandedNetwork.destroy();
            }}

            memoryExpandedNetwork = new vis.Network(container, data, options);

            memoryExpandedNetwork.on('click', function(params) {{
                if (params.nodes.length > 0) {{
                    const nodeId = params.nodes[0];
                    const selectedNode = (currentGraphData.nodes || []).find(n => n.id === nodeId);
                    if (selectedNode) {{
                        openGraphNodeModal(selectedNode);
                        highlightNeighbors(nodeId, modalVisNodes, modalVisEdges, nodes, edges);
                    }}
                }} else {{
                    if (modalVisNodes) modalVisNodes.update(nodes.map(n => ({{ id: n.id, opacity: 1.0 }})));
                    if (modalVisEdges) modalVisEdges.update(edges.map(e => ({{ id: e.id, opacity: 1.0 }})));
                }}
            }});
        }}

        function highlightNeighbors(selectedNodeId, visNodes, visEdges, rawNodes, rawEdges) {{
            const connectedNodeIds = new Set([selectedNodeId]);
            rawEdges.forEach(e => {{
                if (e.from === selectedNodeId) connectedNodeIds.add(e.to);
                if (e.to === selectedNodeId) connectedNodeIds.add(e.from);
            }});

            if (visNodes) {{
                visNodes.update(rawNodes.map(n => ({{
                    id: n.id,
                    opacity: connectedNodeIds.has(n.id) ? 1.0 : 0.2
                }})));
            }}
        }}

        function switchModalViewMode(mode) {{
            currentModalViewMode = mode;
            const btnNet = document.getElementById('modalViewBtnNetwork');
            const btnTree = document.getElementById('modalViewBtnMarkmap');
            const netControls = document.getElementById('modalNetworkControls');
            const treeControls = document.getElementById('modalMarkmapControls');
            const netCanvas = document.getElementById('expandedMemoryGraphCanvas');
            const treeContainer = document.getElementById('expandedMarkmapContainer');
            const netLegend = document.getElementById('modalNetworkLegend');
            const treeLegend = document.getElementById('modalMarkmapLegend');
            const desc = document.getElementById('modalViewDescription');

            const activeBtnClass = 'px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer bg-purple-600/30 text-purple-300 border border-purple-500/40';
            const inactiveBtnClass = 'px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200 border border-transparent';

            if (mode === 'network') {{
                if (btnNet) btnNet.className = activeBtnClass;
                if (btnTree) btnTree.className = inactiveBtnClass;
                if (netControls) netControls.classList.remove('hidden');
                if (treeControls) treeControls.classList.add('hidden');
                if (netCanvas) netCanvas.classList.remove('hidden');
                if (treeContainer) treeContainer.classList.add('hidden');
                if (netLegend) netLegend.classList.remove('hidden');
                if (treeLegend) treeLegend.classList.add('hidden');
                if (desc) desc.innerText = '성단 뷰: 노드 크기(엣지 가중치), 연결 강도, 1-hop 하이라이트 • 물리엔진 기반 유기적 성단 네트워크';
                setTimeout(() => {{
                    if (memoryExpandedNetwork) {{
                        const curSid = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
                        focusSessionInGraph(curSid);
                    }}
                }}, 60);
            }} else {{
                if (btnNet) btnNet.className = inactiveBtnClass;
                if (btnTree) btnTree.className = activeBtnClass;
                if (netControls) netControls.classList.add('hidden');
                if (treeControls) treeControls.classList.remove('hidden');
                if (netCanvas) netCanvas.classList.add('hidden');
                if (treeContainer) treeContainer.classList.remove('hidden');
                if (netLegend) netLegend.classList.add('hidden');
                if (treeLegend) treeLegend.classList.remove('hidden');
                if (desc) desc.innerText = '마인드맵 뷰: 도메인별 문제 ➔ 해결책 접이식 브레인스토밍 생각나무 트리 (원형 노드 클릭 시 가지 접기/펼치기)';
                setTimeout(() => {{
                    initMarkmapTree();
                }}, 60);
            }}
        }}

        function buildMarkmapMarkdown() {{
            const nodes = (currentGraphData && currentGraphData.nodes && currentGraphData.nodes.length > 0)
                ? currentGraphData.nodes
                : (currentMemories || []);
            const edges = (currentGraphData && currentGraphData.edges) ? currentGraphData.edges : [];

            if (!nodes || nodes.length === 0) {{
                return '# 🌿 Giyeok 생각나무\\n- 지식 노드가 아직 없습니다.';
            }}

            const targetSession = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
            let targetSid = targetSession;

            if (targetSession === 'LATEST') {{
                let maxTime = '';
                allRecords.forEach(r => {{
                    if (r.session_id && r.session_id !== 'N/A' && r.timestamp && r.timestamp > maxTime) {{
                        maxTime = r.timestamp;
                        targetSid = r.session_id;
                    }}
                }});
                if (!targetSid && nodes.length > 0) {{
                    targetSid = nodes[0].session_id || 'sess_default';
                }}
            }}

            // 1. 단일 세션 모드: 사용자의 신규/해당 세션 질의가 최상위 ROOT가 됨!
            if (targetSid && targetSid !== 'ALL') {{
                const sessionNodes = nodes.filter(n => n.session_id === targetSid || (n.session_id && n.session_id.includes(targetSid)));
                
                if (sessionNodes.length > 0) {{
                    // 세션의 뿌리 질의 노드 (is_root가 우선, 없으면 가장 이른 노드)
                    const rootNode = sessionNodes.find(n => n.is_root) || sessionNodes[sessionNodes.length - 1] || sessionNodes[0];
                    const rawRootId = String(rootNode.id || '').replace(/^#/, '').trim();
                    const rootMid = rawRootId.substring(0, 8);
                    const rootProb = String(rootNode.problem || rootNode.raw_content || '').trim().replace(/[\\n\\r]+/g, ' ');
                    const rootProbShort = rootProb.length > 60 ? rootProb.substring(0, 60) + '...' : rootProb;
                    const rootSol = String(rootNode.solution || '').trim().replace(/[\\n\\r]+/g, ' ');
                    const rootSolShort = rootSol.length > 90 ? rootSol.substring(0, 90) + '...' : rootSol;

                    let md = `# 🎯 [신규 질의 뿌리] #${{rootMid}} ${{rootProbShort || '(현재 세션 질의)'}} <a href="javascript:void(0)" onclick="openNodeDetail('${{rawRootId}}', event)" class="tb-node-link">🔍 상세 확인</a>\\n`;
                    
                    // 1-1. 적용 해결책 & 아키텍처
                    md += `## 💡 [적용 해결책 & 아키텍처]\\n`;
                    md += `- ${{rootSolShort || '(적용된 솔루션 요약)'}}\\n`;
                    md += `- 🏷️ **메타데이터**: 등급 [${{rootNode.decision || 'BRONZE'}}] | LOC: ${{rootNode.loc || 0}}줄 | 비용: $${{Number(rootNode.cost || 0).toFixed(4)}} | 가중치: ${{Number(rootNode.weight || 1.0).toFixed(2)}}x <a href="javascript:void(0)" onclick="openNodeDetail('${{rawRootId}}', event)" class="tb-node-link">📖 에피소드 소각</a>\\n`;

                    // 1-2. 회수된 과거 연관 지식 (Referenced Past Memories) - 엣지로 연결된 노드들
                    const sessionNodeIds = new Set(sessionNodes.map(n => n.id));
                    const refNodeIds = new Set();
                    edges.forEach(e => {{
                        if (sessionNodeIds.has(e.from) && !sessionNodeIds.has(e.to)) refNodeIds.add(e.to);
                        if (sessionNodeIds.has(e.to) && !sessionNodeIds.has(e.from)) refNodeIds.add(e.from);
                    }});
                    const referencedNodes = nodes.filter(n => refNodeIds.has(n.id));

                    md += `## 🔗 [회수된 과거 연관 지식 (Referenced Memories)]\\n`;
                    if (referencedNodes.length > 0) {{
                        referencedNodes.forEach(ref => {{
                            const refRawId = String(ref.id || '').replace(/^#/, '').trim();
                            const refMid = refRawId.substring(0, 8);
                            const refProb = String(ref.problem || '').trim().replace(/[\\n\\r]+/g, ' ');
                            const refProbShort = refProb.length > 50 ? refProb.substring(0, 50) + '...' : refProb;
                            const refSol = String(ref.solution || '').trim().replace(/[\\n\\r]+/g, ' ');
                            const refSolShort = refSol.length > 70 ? refSol.substring(0, 70) + '...' : refSol;
                            md += `### 📌 #${{refMid}} ${{refProbShort}} <a href="javascript:void(0)" onclick="openNodeDetail('${{refRawId}}', event)" class="tb-node-link">🔍 과거 사례</a>\\n`;
                            md += `- 💡 **해결 요약**: ${{refSolShort}}\\n`;
                            md += `- 🏷️ [${{ref.decision || 'BRONZE'}}] 가중치: ${{Number(ref.weight || 1.0).toFixed(2)}}x\\n`;
                        }});
                    }} else {{
                        md += `- ✨ 독립 세션: 과거 지식의 직접 의존성 없이 새롭게 생성된 지식 에피소드입니다.\\n`;
                    }}

                    // 1-3. 세션 내 후속/서브스텝 질문들
                    const subNodes = sessionNodes.filter(n => n.id !== rootNode.id);
                    if (subNodes.length > 0) {{
                        md += `## 🌿 [세션 세부 실행 단계 (Sub-steps & Follow-ups)]\\n`;
                        subNodes.forEach(sub => {{
                            const subRawId = String(sub.id || '').replace(/^#/, '').trim();
                            const subMid = subRawId.substring(0, 8);
                            const subProb = String(sub.problem || '').trim().replace(/[\\n\\r]+/g, ' ');
                            const subProbShort = subProb.length > 50 ? subProb.substring(0, 50) + '...' : subProb;
                            const subSol = String(sub.solution || '').trim().replace(/[\\n\\r]+/g, ' ');
                            const subSolShort = subSol.length > 70 ? subSol.substring(0, 70) + '...' : subSol;
                            md += `### 🔄 #${{subMid}} ${{subProbShort}} <a href="javascript:void(0)" onclick="openNodeDetail('${{subRawId}}', event)" class="tb-node-link">🔍 확인</a>\\n`;
                            md += `- 💡 ${{subSolShort}}\\n`;
                            md += `- 🏷️ 등급 [${{sub.decision || 'BRONZE'}}] | LOC: ${{sub.loc || 0}}줄\\n`;
                        }});
                    }}

                    return md;
                }}
            }}

            // 2. 전체(ALL) 세션 모드: 세션별 / 질의별 뿌리 노드 그룹화 (최신순 정렬)
            const sessionMap = {{}};
            nodes.forEach(n => {{
                const sid = n.session_id || 'sess_default';
                if (!sessionMap[sid]) {{
                    sessionMap[sid] = [];
                }}
                sessionMap[sid].push(n);
            }});

            let md = `# 🌿 Giyeok 생각나무 (${{nodes.length}} Pure Fruits - 전체 세션)\\n`;
            
            // 세션별로 뿌리 노드를 최상단에 배치
            Object.keys(sessionMap).forEach(sid => {{
                const sNodes = sessionMap[sid];
                const rootNode = sNodes.find(n => n.is_root) || sNodes[sNodes.length - 1] || sNodes[0];
                const rawId = String(rootNode.id || '').replace(/^#/, '').trim();
                const sidShort = sid.substring(0, 8);
                const prob = String(rootNode.problem || rootNode.raw_content || '').trim().replace(/[\\n\\r]+/g, ' ');
                const pShort = prob.length > 50 ? prob.substring(0, 50) + '...' : prob;
                const sol = String(rootNode.solution || '').trim().replace(/[\\n\\r]+/g, ' ');
                const sShort = sol.length > 70 ? sol.substring(0, 70) + '...' : sol;

                md += `## 🎯 [세션 ${{sidShort}}] 👑 ${{pShort}} <a href="javascript:void(0)" onclick="openNodeDetail('${{rawId}}', event)" class="tb-node-link">🔍 상세</a>\\n`;
                md += `- 💡 **해결책**: ${{sShort || '(해결책 요약)'}}\\n`;
                md += `- 🏷️ **메타**: [${{rootNode.decision || 'BRONZE'}}] | LOC: ${{rootNode.loc || 0}}줄 | 세션 노드: ${{sNodes.length}}개 <a href="javascript:void(0)" onclick="selectSessionFilter('${{sid}}')" class="tb-node-link">🎯 이 세션 필터링</a>\\n`;
                
                const otherNodes = sNodes.filter(n => n.id !== rootNode.id);
                if (otherNodes.length > 0) {{
                    md += `### 🌿 세션 세부 턴 (${{otherNodes.length}}개 단계)\\n`;
                    otherNodes.slice(0, 3).forEach(on => {{
                        const oRawId = String(on.id || '').replace(/^#/, '').trim();
                        const oProb = String(on.problem || '').trim().replace(/[\\n\\r]+/g, ' ');
                        const opShort = oProb.length > 40 ? oProb.substring(0, 40) + '...' : oProb;
                        md += `- 📌 #${{on.id.substring(0, 8)}} ${{opShort}} <a href="javascript:void(0)" onclick="openNodeDetail('${{oRawId}}', event)" class="tb-node-link">🔍 확인</a>\\n`;
                    }});
                }}
            }});

            return md;
        }}

        function initMarkmapTree() {{
            const svg = document.getElementById('markmapSvg');
            const container = document.getElementById('expandedMarkmapContainer');
            if (!svg || !window.markmap) return;

            if (!markmapTransformer) {{
                markmapTransformer = new markmap.Transformer();
            }}

            const md = buildMarkmapMarkdown();
            const {{ root }} = markmapTransformer.transform(md);

            if (markmapInstance) {{
                markmapInstance.setData(root);
                markmapInstance.fit();
            }} else {{
                markmapInstance = markmap.Markmap.create(svg, {{
                    duration: 350,
                    nodeMinHeight: 20,
                    spacingHorizontal: 80,
                    spacingVertical: 10,
                    paddingX: 12,
                    autoFit: true
                }}, root);
            }}

            // 🍎 맥북 트랙패드 두 손가락 스크롤 / 핀치 줌 정밀 바인딩
            if (container && !container._trackpadZoomAttached) {{
                container._trackpadZoomAttached = true;
                container.addEventListener('wheel', function(e) {{
                    e.preventDefault();
                    if (!markmapInstance) return;
                    // deltaY < 0 (위로 스크롤/핀치 아웃: 확대), deltaY > 0 (아래로 스크롤/핀치 인: 축소)
                    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
                    try {{
                        markmapInstance.rescale(zoomFactor);
                    }} catch(err) {{}}
                }}, {{ passive: false }});
            }}
        }}

        function zoomInMarkmap() {{
            if (markmapInstance) {{
                try {{
                    markmapInstance.rescale(1.25);
                }} catch(e) {{}}
            }}
        }}

        function zoomOutMarkmap() {{
            if (markmapInstance) {{
                try {{
                    markmapInstance.rescale(0.8);
                }} catch(e) {{}}
            }}
        }}

        function zoomInNetwork() {{
            if (memoryExpandedNetwork) {{
                try {{
                    const curScale = memoryExpandedNetwork.getScale();
                    memoryExpandedNetwork.moveTo({{ scale: curScale * 1.25, animation: {{ duration: 250, easingFunction: 'easeInOutQuad' }} }});
                }} catch(e) {{}}
            }}
        }}

        function zoomOutNetwork() {{
            if (memoryExpandedNetwork) {{
                try {{
                    const curScale = memoryExpandedNetwork.getScale();
                    memoryExpandedNetwork.moveTo({{ scale: curScale * 0.8, animation: {{ duration: 250, easingFunction: 'easeInOutQuad' }} }});
                }} catch(e) {{}}
            }}
        }}

        function fitMarkmapTree() {{
            if (markmapInstance) {{
                markmapInstance.fit();
            }}
        }}

        function expandAllMarkmap() {{
            if (markmapInstance && markmapInstance.state && markmapInstance.state.data) {{
                function setFold(node, fold) {{
                    if (node.children) {{
                        node.children.forEach(c => setFold(c, fold));
                    }}
                    node.payload = {{ ...(node.payload || {{}}), fold }};
                }}
                setFold(markmapInstance.state.data, 0);
                markmapInstance.renderData();
                markmapInstance.fit();
            }}
        }}

        function collapseAllMarkmap() {{
            if (markmapInstance && markmapInstance.state && markmapInstance.state.data) {{
                function setFold(node) {{
                    if (node.children) {{
                        node.children.forEach(c => {{
                            c.payload = {{ ...(c.payload || {{}}), fold: 1 }};
                            setFold(c);
                        }});
                    }}
                }}
                setFold(markmapInstance.state.data);
                markmapInstance.renderData();
                markmapInstance.fit();
            }}
        }}

        function openExpandedGraphModal() {{
            const modal = document.getElementById('expandedGraphModal');
            if (modal) {{
                modal.classList.remove('hidden');
                setTimeout(() => {{
                    const curSid = document.getElementById('sessionSelect') ? document.getElementById('sessionSelect').value : 'ALL';
                    if (currentModalViewMode === 'network') {{
                        initExpandedMemoryGraph(currentGraphData);
                        focusSessionInGraph(curSid);
                    }} else {{
                        initMarkmapTree();
                    }}
                }}, 60);
            }}
        }}

        function closeExpandedGraphModal() {{
            const modal = document.getElementById('expandedGraphModal');
            if (modal) modal.classList.add('hidden');
        }}

        document.addEventListener('keydown', e => {{
            if (e.key === 'Escape') {{
                closeSavingsInfoModal();
                closeHealingModal();
                closeGitPullModal();
                closeGraphNodeModal();
                closeExpandedGraphModal();
            }}
        }});

        function toggleGraphPhysics() {{
            isMiniPhysicsEnabled = !isMiniPhysicsEnabled;
            const btn = document.getElementById('toggleMiniPhysicsBtn');
            if (memoryMiniNetwork) {{
                memoryMiniNetwork.setOptions({{ physics: {{ enabled: isMiniPhysicsEnabled }} }});
            }}
            if (btn) {{
                btn.className = isMiniPhysicsEnabled 
                    ? 'px-2.5 py-1.5 bg-purple-600/30 hover:bg-purple-600/50 text-purple-300 text-xs font-bold rounded-xl border border-purple-500/40 transition-all flex items-center gap-1 cursor-pointer'
                    : 'px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-400 text-xs font-bold rounded-xl border border-slate-700 transition-all flex items-center gap-1 cursor-pointer';
            }}
        }}

        function toggleModalGraphPhysics() {{
            isModalPhysicsEnabled = !isModalPhysicsEnabled;
            const btn = document.getElementById('toggleModalPhysicsBtn');
            if (memoryExpandedNetwork) {{
                memoryExpandedNetwork.setOptions({{ physics: {{ enabled: isModalPhysicsEnabled }} }});
            }}
            if (btn) {{
                btn.innerHTML = isModalPhysicsEnabled 
                    ? '<i class="fa-solid fa-atom"></i> 물리엔진 끄기'
                    : '<i class="fa-solid fa-play text-emerald-400"></i> 물리엔진 켜기';
            }}
        }}

        function fitMemoryGraph() {{
            if (memoryMiniNetwork) {{
                memoryMiniNetwork.fit({{ animation: {{ duration: 500, easingFunction: 'easeInOutQuad' }} }});
            }}
        }}

        function fitExpandedMemoryGraph() {{
            if (memoryExpandedNetwork) {{
                memoryExpandedNetwork.fit({{ animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
            }}
        }}

        function filterExpandedMemoryGraph() {{
            const filterVal = document.getElementById('modalGraphTierFilter').value;
            if (!currentGraphData || !currentGraphData.nodes) return;

            let filteredNodes = currentGraphData.nodes;
            if (filterVal !== 'ALL') {{
                filteredNodes = currentGraphData.nodes.filter(n => (n.decision || '').toUpperCase() === filterVal);
            }}
            const filteredIds = new Set(filteredNodes.map(n => n.id));
            const filteredEdges = (currentGraphData.edges || []).filter(e => filteredIds.has(e.from) && filteredIds.has(e.to));

            initExpandedMemoryGraph({{ nodes: filteredNodes, edges: filteredEdges }});
        }}

        // 🎯 오직 그래프 카메라만 포커스 이동 (모달 팝업 차단)
        function focusNodeInGraph(nodeId, event) {{
            if (event) event.stopPropagation();
            if (currentDashboardTab !== 'memory') {{
                switchDashboardTab('memory');
            }}
            
            const cleanId = (nodeId || '').replace(/^#/, '').trim();
            if (memoryMiniNetwork) {{
                memoryMiniNetwork.focus(cleanId, {{ scale: 1.5, animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
                try {{ memoryMiniNetwork.selectNodes([cleanId]); }} catch(e) {{}}
            }}
            const expModal = document.getElementById('expandedGraphModal');
            if (expModal && !expModal.classList.contains('hidden') && memoryExpandedNetwork) {{
                memoryExpandedNetwork.focus(cleanId, {{ scale: 1.5, animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }} }});
                try {{ memoryExpandedNetwork.selectNodes([cleanId]); }} catch(e) {{}}
            }}
        }}

        // 🌌 선택한 세션의 뿌리 노드(Root Node)로 성단형 그래프 카메라 자동 포커스 및 하이라이트
        function focusSessionInGraph(targetSession) {{
            if (!targetSession) return;
            const nodes = (currentGraphData && currentGraphData.nodes) ? currentGraphData.nodes : [];
            const edges = (currentGraphData && currentGraphData.edges) ? currentGraphData.edges : [];
            if (nodes.length === 0) return;

            let targetSid = targetSession;
            if (targetSession === 'LATEST') {{
                let maxTime = '';
                allRecords.forEach(r => {{
                    if (r.session_id && r.session_id !== 'N/A' && r.timestamp && r.timestamp > maxTime) {{
                        maxTime = r.timestamp;
                        targetSid = r.session_id;
                    }}
                }});
                if (!targetSid && nodes.length > 0) {{
                    targetSid = nodes[0].session_id || 'sess_default';
                }}
            }}

            if (targetSession === 'ALL' || !targetSid) {{
                const resetNodes = nodes.map(n => ({{
                    id: n.id,
                    opacity: 1.0,
                    borderWidth: 2,
                    color: n.color
                }}));
                if (miniVisNodes) miniVisNodes.update(resetNodes);
                if (modalVisNodes) modalVisNodes.update(resetNodes);
                if (miniVisEdges) miniVisEdges.update(edges.map(e => ({{ id: e.id, opacity: 1.0 }})));
                if (modalVisEdges) modalVisEdges.update(edges.map(e => ({{ id: e.id, opacity: 1.0 }})));
                return;
            }}

            const sessionNodes = nodes.filter(n => n.session_id === targetSid || (n.session_id && n.session_id.includes(targetSid)));
            if (sessionNodes.length === 0) return;

            // 세션 뿌리 노드 식별 (is_root가 우선, 없으면 가장 이른 노드)
            const rootNode = sessionNodes.find(n => n.is_root) || sessionNodes[sessionNodes.length - 1] || sessionNodes[0];
            const sessionNodeIds = new Set(sessionNodes.map(n => n.id));

            // 연결된 1-hop 연관 노드 식별
            const connectedNodeIds = new Set(sessionNodeIds);
            edges.forEach(e => {{
                if (sessionNodeIds.has(e.from)) connectedNodeIds.add(e.to);
                if (sessionNodeIds.has(e.to)) connectedNodeIds.add(e.from);
            }});

            const updateNodes = nodes.map(n => {{
                const isThisRoot = (n.id === rootNode.id);
                const isSessionNode = sessionNodeIds.has(n.id);
                const isConnected = connectedNodeIds.has(n.id);
                return {{
                    id: n.id,
                    opacity: isConnected ? 1.0 : 0.15,
                    borderWidth: isThisRoot ? 5 : (isSessionNode ? 3 : 2),
                    color: isThisRoot ? {{
                        border: '#f59e0b',
                        background: n.color ? (n.color.background || '#f59e0b') : '#f59e0b',
                        highlight: {{ border: '#fbbf24', background: '#f59e0b' }}
                    }} : n.color
                }};
            }});

            if (miniVisNodes) miniVisNodes.update(updateNodes);
            if (modalVisNodes) modalVisNodes.update(updateNodes);

            const updateEdges = edges.map(e => ({{
                id: e.id,
                opacity: (connectedNodeIds.has(e.from) && connectedNodeIds.has(e.to)) ? 1.0 : 0.08
            }}));
            if (miniVisEdges) miniVisEdges.update(updateEdges);
            if (modalVisEdges) modalVisEdges.update(updateEdges);

            // 🚀 선택된 세션의 뿌리 노드로 카메라 포커스 이동 & 노드 선택
            if (memoryMiniNetwork) {{
                memoryMiniNetwork.focus(rootNode.id, {{
                    scale: 1.35,
                    animation: {{ duration: 750, easingFunction: 'easeInOutQuad' }}
                }});
                try {{ memoryMiniNetwork.selectNodes([rootNode.id]); }} catch(e) {{}}
            }}
            if (memoryExpandedNetwork) {{
                memoryExpandedNetwork.focus(rootNode.id, {{
                    scale: 1.35,
                    animation: {{ duration: 750, easingFunction: 'easeInOutQuad' }}
                }});
                try {{ memoryExpandedNetwork.selectNodes([rootNode.id]); }} catch(e) {{}}
            }}
        }}

        // 📖 카드 또는 마크맵 링크 클릭 시 상세 정보 모달 열기
        function openNodeDetail(nodeId, event) {{
            if (event) {{
                try {{ event.stopPropagation(); }} catch(e) {{}}
            }}
            const cleanId = String(nodeId || '').replace(/^#/, '').trim();
            const nodes = (currentGraphData && currentGraphData.nodes && currentGraphData.nodes.length > 0)
                ? currentGraphData.nodes
                : (currentMemories || []);

            let selectedNode = nodes.find(n => String(n.id || '').replace(/^#/, '').trim() === cleanId);
            if (!selectedNode && currentMemories) {{
                selectedNode = currentMemories.find(n => String(n.id || '').replace(/^#/, '').trim() === cleanId);
            }}
            if (selectedNode) {{
                openGraphNodeModal(selectedNode);
            }}
        }}
        window.openNodeDetail = openNodeDetail;

        function openGraphNodeModal(node) {{
            const modal = document.getElementById('graphNodeModal');
            if (!modal) return;

            currentModalNodeId = (node.id || '').replace(/^#/, '').trim();
            const badge = document.getElementById('modalNodeBadge');
            const idEl = document.getElementById('modalNodeId');
            const metaEl = document.getElementById('modalNodeMeta');
            const probEl = document.getElementById('modalNodeProblem');
            const solEl = document.getElementById('modalNodeSolution');

            const dec = (node.decision || 'BRONZE').toUpperCase();
            if (badge) {{
                badge.innerText = dec;
                let bClass = 'px-3 py-1 font-bold rounded-xl text-xs border ';
                if (dec.includes('GOLD')) bClass += 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                else if (dec.includes('PLATINUM')) bClass += 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
                else if (dec.includes('SILVER')) bClass += 'bg-slate-700/40 text-slate-200 border-slate-400/40';
                else bClass += 'bg-amber-900/30 text-amber-300 border-amber-600/40';
                badge.className = bClass;
            }}

            if (idEl) idEl.innerText = `#${{currentModalNodeId}}`;
            if (metaEl) metaEl.innerText = `승격 가중치: ${{node.weight ? node.weight.toFixed(2) : '1.00'}}x | 코드 LOC: ${{node.loc || 0}}줄 | 발생 비용: $${{(node.cost || 0.0).toFixed(4)}} | 시각: ${{node.timestamp || 'N/A'}}`;
            if (probEl) probEl.innerText = node.problem || '(문제 요구사항 없음)';
            if (solEl) solEl.innerText = node.solution || '(해결책 없음)';

            modal.classList.remove('hidden');
        }}

        function closeGraphNodeModal() {{
            const modal = document.getElementById('graphNodeModal');
            if (modal) modal.classList.add('hidden');
        }}

        async function executeNeuralize(nodeId) {{
            if (!nodeId) return;
            const cleanId = String(nodeId).replace(/^#/, '').trim();
            const shortId = cleanId.length > 8 ? cleanId.substring(0, 8) : cleanId;
            const ok = confirm(`⚡ [Neuralizer] 이 기억 노드(#${{shortId}}...)와 연결선만 정밀 소각하시겠습니까?\n\n(연결된 다른 주변 기억은 안전하게 보존됩니다)`);
            if (!ok) return;

            try {{
                const res = await fetch(`http://127.0.0.1:18080/v1/dashboard/memories/neuralize/${{encodeURIComponent(cleanId)}}`, {{ method: 'POST' }});
                if (res.ok) {{
                    const data = await res.json();
                    alert(`⚡ Neuralizer 소각 완료!\n- 노드 ID: #${{shortId}}...\n- 제거된 연관 엣지 수: ${{data.deleted_edges_count || 0}}개`);
                    closeGraphNodeModal();
                    
                    // 1. vis.DataSet에서 즉각 삭제 (0ms 즉시 화면 제거)
                    if (miniVisNodes) {{
                        try {{ miniVisNodes.remove(cleanId); }} catch(e) {{}}
                        try {{ miniVisNodes.remove(nodeId); }} catch(e) {{}}
                    }}
                    if (modalVisNodes) {{
                        try {{ modalVisNodes.remove(cleanId); }} catch(e) {{}}
                        try {{ modalVisNodes.remove(nodeId); }} catch(e) {{}}
                    }}

                    // 2. 인메모리 데이터셋 필터링
                    if (currentGraphData && currentGraphData.nodes) {{
                        currentGraphData.nodes = currentGraphData.nodes.filter(n => String(n.id) !== cleanId && String(n.id) !== String(nodeId));
                    }}
                    if (currentGraphData && currentGraphData.edges) {{
                        currentGraphData.edges = currentGraphData.edges.filter(e => String(e.from) !== cleanId && String(e.to) !== cleanId && String(e.from) !== String(nodeId) && String(e.to) !== String(nodeId));
                    }}
                    if (currentMemories) {{
                        currentMemories = currentMemories.filter(m => String(m.id) !== cleanId && String(m.id) !== String(nodeId));
                    }}
                    if (currentTopEdges) {{
                        currentTopEdges = currentTopEdges.filter(e => String(e.source_id) !== cleanId && String(e.target_id) !== cleanId && String(e.source_id) !== String(nodeId) && String(e.target_id) !== String(nodeId));
                    }}

                    // 3. 테이블 및 KPI 뷰 즉시 재렌더링
                    renderMemoryView(currentMemories, currentMemStats, currentGraphData, currentTopEdges);
                    
                    // 3-1. 생각나무 마인드맵(Markmap) 즉시 0ms 재렌더링
                    try {{
                        initMarkmapTree();
                    }} catch(errMarkmap) {{
                        console.warn('Markmap refresh warning:', errMarkmap);
                    }}

                    // 4. 백그라운드 동기화
                    setTimeout(fetchLiveDashboardStats, 300);
                }} else {{
                    alert('Neuralizer 소각 실패: 서버 오류');
                }}
            }} catch(e) {{
                alert(`Neuralizer 소각 오류: ${{e.message}}`);
            }}
        }}

        function onModalNeuralizeClick() {{
            if (currentModalNodeId) {{
                executeNeuralize(currentModalNodeId);
            }}
        }}

        function renderTopEdges(edgesList) {{
            const tbody = document.getElementById('topEdgesTableBody');
            if (!tbody) return;

            const list = edgesList || currentTopEdges || [];
            if (list.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-slate-500 font-mono">가중치 승격 엣지 레코드가 아직 없습니다. (고난도 작업 후 자동 갱신됩니다)</td></tr>';
                return;
            }}

            let html = '';
            list.forEach((e, idx) => {{
                const sId = String(e.source_id || '');
                const sIdShort = sId.length > 10 ? sId.substring(0, 10) + '...' : sId;
                const tId = String(e.target_id || '');
                const tIdShort = tId.length > 10 ? tId.substring(0, 10) + '...' : tId;
                const dec = e.decision || 'BRONZE';
                const loc = e.loc || 0;
                const cost = e.cost || 0.0;
                const weight = e.weight || 1.0;
                const prob = String(e.problem || '');
                const probShort = prob.length > 45 ? prob.substring(0, 45) + '...' : prob;

                let badgeClass = 'bg-slate-800 text-slate-300 border-slate-600/40';
                if (dec.includes('GOLD')) badgeClass = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                else if (dec.includes('PLATINUM')) badgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
                else if (dec.includes('SILVER')) badgeClass = 'bg-slate-700/40 text-slate-200 border-slate-400/40';

                html += `
                <tr class="hover:bg-slate-800/50 transition-colors border-b border-slate-800/80 cursor-pointer" onclick="openNodeDetail('${{sId}}', event)">
                    <td class="px-4 py-3 font-mono text-yellow-300 font-bold">#${{idx+1}}</td>
                    <td class="px-4 py-3 font-mono text-purple-300 text-xs" title="${{sId}}">${{sIdShort}}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2 py-0.5 text-xs font-semibold rounded-full border ${{badgeClass}}">${{dec}}</span>
                    </td>
                    <td class="px-4 py-3 text-right font-mono text-emerald-400">${{loc}}줄</td>
                    <td class="px-4 py-3 text-right font-mono text-slate-300">$${{cost.toFixed(4)}}</td>
                    <td class="px-4 py-3 text-right font-mono font-extrabold text-amber-300">${{weight.toFixed(2)}}x</td>
                    <td class="px-4 py-3 font-mono text-slate-400 text-xs" title="${{tId}}">${{tIdShort}}</td>
                    <td class="px-4 py-3 text-slate-200 text-xs truncate max-w-xs" title="${{prob}}">${{probShort}}</td>
                </tr>
                `;
            }});
            tbody.innerHTML = html;
        }}

        function renderMemoryView(memoriesList, memStats, graphData, topEdges) {{
            const list = memoriesList || currentMemories || [];
            const stats = memStats || currentMemStats || {{}};

            const totalEl = document.getElementById('kpiMemTotal');
            const recallEl = document.getElementById('kpiMemRecallHits');
            const savedEl = document.getElementById('kpiMemSavedCredits');
            const weightEl = document.getElementById('kpiMemMaxWeight');
            const badgeEl = document.getElementById('memTabCountBadge');

            if (totalEl) totalEl.innerHTML = `${{stats.total_memories || list.length}} <span class="text-sm font-normal text-slate-400">Episodes</span>`;
            if (recallEl) recallEl.innerHTML = `${{stats.recall_hits || 0}} <span class="text-sm font-normal text-slate-400">Hits</span>`;
            if (savedEl) savedEl.innerHTML = `${{(stats.saved_credits || 0.0).toFixed(2)}} <span class="text-sm font-normal text-slate-400">Cr</span>`;
            if (weightEl) weightEl.innerHTML = `${{(stats.max_edge_weight || 1.0).toFixed(2)}} <span class="text-sm font-normal text-slate-400">x</span>`;
            if (badgeEl) badgeEl.innerText = `${{stats.total_memories || list.length}}건`;

            renderTopEdges(topEdges || currentTopEdges);

            const searchInput = document.getElementById('memSearchInput');
            if (searchInput && searchInput.value.trim()) {{
                performMemorySearch(searchInput.value.trim());
            }} else {{
                renderDefaultRecentMemoryCards();
            }}

            const sessionSelect = document.getElementById('sessionSelect');
            const targetSession = sessionSelect ? sessionSelect.value : 'ALL';

            const filtered = (targetSession && targetSession !== 'ALL')
                ? list.filter(m => (m.session_id && String(m.session_id).toLowerCase().includes(targetSession.toLowerCase())) || (m.tags && m.tags.includes(targetSession)))
                : list;

            const tbody = document.getElementById('memoryStreamTableBody');
            if (!tbody) return;

            if (filtered.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="8" class="text-center py-8 text-slate-500 font-mono">기억저장소에 적재된 문제-해결 에피소드가 아직 없습니다. (첫 프롬프트 요청 후 3초 내 실시간 자동 반영됩니다)</td></tr>';
                return;
            }}

            let html = '';
            filtered.forEach((m, idx) => {{
                const sid = String(m.session_id || 'sess_default');
                const sidShort = sid.length > 12 ? sid.substring(0, 12) + '...' : sid;
                const dec = m.decision || 'UNKNOWN';
                const loc = m.loc || 0;
                const cost = m.cost || 0.0;
                const prob = String(m.problem || m.raw_content || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                const sol = String(m.solution || dec).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                const timeStr = String(m.created_at || 'N/A');
                const mid = String(m.id || `node_${{idx+1}}`);
                const midShort = mid.length > 8 ? mid.substring(0, 8) + '...' : mid;

                let badgeClass = 'bg-slate-800 text-slate-300 border-slate-600/40';
                if (dec.includes('GOLD')) badgeClass = 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
                else if (dec.includes('SILVER')) badgeClass = 'bg-slate-700/40 text-slate-200 border-slate-400/40';
                else if (dec.includes('BRONZE')) badgeClass = 'bg-amber-900/30 text-amber-300 border-amber-600/40';
                else if (dec.includes('PLATINUM')) badgeClass = 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';

                html += `
                <tr class="hover:bg-slate-800/50 transition-colors border-b border-slate-800/80">
                    <td class="px-4 py-3 font-mono text-purple-300 font-bold cursor-pointer" onclick="openNodeDetail('${{mid}}', event)">#${{midShort}}</td>
                    <td class="px-4 py-3 font-mono text-slate-300 text-xs" title="${{sid}}">${{sidShort}}</td>
                    <td class="px-4 py-3 text-center">
                        <span class="px-2.5 py-1 rounded-full text-xs font-bold border ${{badgeClass}}">${{dec}}</span>
                    </td>
                    <td class="px-4 py-3 font-mono text-center text-xs ${{loc > 0 ? 'text-emerald-400 font-bold' : 'text-slate-500'}}">+${{loc}}</td>
                    <td class="px-4 py-3 font-mono text-center text-xs text-yellow-400">$${{cost.toFixed(4)}}</td>
                    <td class="px-4 py-3 text-xs text-slate-300 max-w-[280px] truncate cursor-pointer hover:text-purple-300" onclick="openNodeDetail('${{mid}}', event)" title="${{prob}}">${{prob}}</td>
                    <td class="px-4 py-3 font-mono text-xs text-slate-400 text-center">${{timeStr}}</td>
                    <td class="px-4 py-3 text-center">
                        <button onclick="executeNeuralize('${{mid}}')" title="이 기억 노드만 정밀 소각"
                                class="px-2 py-1 bg-rose-950/40 hover:bg-rose-900 border border-rose-500/40 text-rose-300 rounded-lg text-xs font-bold transition-all cursor-pointer">
                            <i class="fa-solid fa-bolt-lightning text-amber-400 mr-1"></i>소각
                        </button>
                    </td>
                </tr>
                `;
            }});
            tbody.innerHTML = html;
        }}

        let searchDebounceTimer = null;
        function onMemorySearchRealtime(val) {{
            if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {{
                performMemorySearch(val);
            }}, 150);
        }}

        function onMemorySearchInput(event) {{
            if (event.key === 'Enter') {{
                if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
                performMemorySearch();
            }}
        }}

        function renderDefaultRecentMemoryCards() {{
            const resultsContainer = document.getElementById('memSearchResults');
            if (!resultsContainer) return;
            
            const pool = (currentGraphData && currentGraphData.nodes && currentGraphData.nodes.length > 0)
                ? currentGraphData.nodes
                : (currentMemories || []);
                
            if (!pool || pool.length === 0) {{
                resultsContainer.innerHTML = '<div class="text-center py-10 text-xs text-slate-500 font-mono">💡 검색어를 입력하여 연관 지식을 실시간 검색하세요.</div>';
                return;
            }}
            
            const topItems = pool.slice(0, 4).map(item => ({{
                id: item.id,
                problem: item.problem || item.label || item.title || item.raw_content || '',
                solution: item.solution || item.decision || 'N/A',
                raw_content: item.text || item.raw_content || '',
                decision: item.decision || 'BRONZE',
                session_id: item.session_id || 'sess_default',
                score: 0.95
            }}));
            renderSearchResultsCards(topItems, null, "🌟 최근 축적된 순수 지식 열매 (Top Fruits)");
        }}

        function renderSearchResultsCards(searchResults, query, headerTitle) {{
            const resultsContainer = document.getElementById('memSearchResults');
            if (!resultsContainer) return;

            if (!searchResults || searchResults.length === 0) {{
                resultsContainer.innerHTML = `<div class="text-center py-10 text-xs text-slate-500 font-mono">❌ "${{query || ''}}" 와 일치하거나 연관된 기억이 없습니다.</div>`;
                return;
            }}

            let cardsHtml = '';
            if (headerTitle) {{
                cardsHtml += `<div class="text-[11px] font-bold text-purple-400 mb-2 flex items-center gap-1.5"><i class="fa-solid fa-sparkles"></i> ${{headerTitle}}</div>`;
            }}

            searchResults.forEach((r, idx) => {{
                const prob = (r.problem || r.raw_content || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                const sol = (r.solution || r.decision || 'N/A').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                const scorePct = r.score ? Math.round(r.score * 100) : 95;
                const sid = String(r.session_id || 'sess_default');
                const sidShort = sid.length > 10 ? sid.substring(0, 10) + '...' : sid;
                const rid = String(r.id || `node_${{idx+1}}`).replace(/^#/, '').trim();

                cardsHtml += `
                <div class="p-3.5 rounded-xl bg-slate-800/80 border border-purple-500/30 hover:border-purple-400 transition-all shadow-md">
                    <div class="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-slate-700/60">
                        <div class="flex items-center gap-2">
                            <span class="px-2 py-0.5 bg-purple-500/20 text-purple-300 rounded font-mono text-xs font-bold">🎯 ${{scorePct}}% 일치</span>
                            <span class="text-xs font-mono text-slate-400">세션: ${{sidShort}}</span>
                            ${{r.decision ? `<span class="px-2 py-0.5 bg-yellow-500/20 text-yellow-300 rounded text-[10px] font-bold border border-yellow-500/30">${{r.decision}}</span>` : ''}}
                        </div>
                        <div class="flex items-center gap-1.5">
                            <button onclick="focusNodeInGraph('${{rid}}', event)" title="우측 생각나무에서 노드 위치로 줌인"
                                    class="px-2.5 py-1 bg-purple-600/30 hover:bg-purple-600/60 text-purple-200 border border-purple-400/40 rounded-lg text-[10px] font-bold transition-all flex items-center gap-1 cursor-pointer">
                                <i class="fa-solid fa-crosshairs text-purple-300"></i> 포커스
                            </button>
                            <button onclick="openNodeDetail('${{rid}}', event)" title="상세 정보 및 소각 모달 열기"
                                    class="px-2.5 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg text-[10px] font-semibold transition-all cursor-pointer">
                                상세 보기
                            </button>
                        </div>
                    </div>
                    <div class="mb-1.5 cursor-pointer" onclick="openNodeDetail('${{rid}}', event)">
                        <span class="text-xs font-bold text-purple-300">📌 문제/요구사항:</span>
                        <div class="text-xs text-slate-200 mt-0.5 leading-relaxed line-clamp-2">${{prob}}</div>
                    </div>
                    <div class="cursor-pointer" onclick="openNodeDetail('${{rid}}', event)">
                        <span class="text-xs font-bold text-emerald-300">💡 적용 해결책:</span>
                        <div class="text-xs text-slate-300 mt-0.5 font-mono bg-slate-900/70 p-2 rounded-lg border border-slate-700/40 line-clamp-2">${{sol}}</div>
                    </div>
                </div>
                `;
            }});
            resultsContainer.innerHTML = cardsHtml;
        }}

        async function performMemorySearch(queryParam) {{
            const input = document.getElementById('memSearchInput');
            const query = (typeof queryParam === 'string' ? queryParam : (input ? input.value : '')).trim();
            const resultsContainer = document.getElementById('memSearchResults');
            if (!resultsContainer) return;

            if (!query) {{
                renderDefaultRecentMemoryCards();
                return;
            }}

            let searchResults = [];
            try {{
                let res = null;
                try {{
                    res = await fetch(`http://127.0.0.1:18080/v1/dashboard/memories/search?q=${{encodeURIComponent(query)}}`);
                }} catch(e1) {{
                    try {{
                        res = await fetch(`http://localhost:18080/v1/dashboard/memories/search?q=${{encodeURIComponent(query)}}`);
                    }} catch(e2) {{}}
                }}
                if (res && res.ok) {{
                    const data = await res.json();
                    if (data.results && data.results.length > 0) {{
                        searchResults = data.results;
                    }}
                }}
            }} catch (e) {{}}

            // 클라이언트 사이드 고속 시맨틱/키워드 다단계 검색 (0ms 즉시 폴백)
            if (searchResults.length === 0) {{
                const qLower = query.toLowerCase();
                const allPool = [];
                
                if (currentGraphData && currentGraphData.nodes) {{
                    currentGraphData.nodes.forEach(n => {{
                        allPool.push({{
                            id: n.id,
                            problem: n.problem || n.title || n.label || '',
                            solution: n.solution || '',
                            raw_content: n.text || n.problem || '',
                            decision: n.decision || 'BRONZE',
                            session_id: n.session_id || 'sess_default',
                            tags: n.tags || [],
                            score: 0.90,
                            loc: n.loc || 0
                        }});
                    }});
                }}
                if (currentMemories) {{
                    currentMemories.forEach(m => {{
                        if (!allPool.some(p => String(p.id).replace(/^#/, '') === String(m.id).replace(/^#/, ''))) {{
                            allPool.push(m);
                        }}
                    }});
                }}

                const tokens = qLower.split(/[\\s,\\.\\-_]+/).filter(t => t.length >= 1);
                const matched = [];

                allPool.forEach(item => {{
                    const prob = (item.problem || item.raw_content || '').toLowerCase();
                    const sol = (item.solution || '').toLowerCase();
                    const tags = (item.tags || []).map(t => String(t).toLowerCase()).join(' ');
                    const fullText = `${{prob}} ${{sol}} ${{tags}}`;

                    let matchCount = 0;
                    tokens.forEach(tok => {{
                        if (fullText.includes(tok)) matchCount++;
                    }});

                    if (matchCount > 0 || fullText.includes(qLower)) {{
                        const matchRatio = matchCount / Math.max(1, tokens.length);
                        const baseScore = fullText.includes(qLower) ? 0.95 : (0.65 + matchRatio * 0.30);
                        matched.push({{
                            ...item,
                            score: baseScore
                        }});
                    }}
                }});

                matched.sort((a, b) => (b.score || 0) - (a.score || 0));
                searchResults = matched.slice(0, 10);
            }}

            renderSearchResultsCards(searchResults, query);
        }}

        let livePollIntervalTimer = null;
        let currentPollIntervalSeconds = 5; // default 5초

        function initPollInterval() {{
            const saved = localStorage.getItem('tierbridge_poll_interval');
            if (saved !== null && saved !== undefined) {{
                const parsed = parseInt(saved, 10);
                if (!isNaN(parsed) && parsed >= 0) {{
                    currentPollIntervalSeconds = parsed;
                }}
            }} else {{
                currentPollIntervalSeconds = 5;
            }}
            applyPollInterval(currentPollIntervalSeconds, false);
        }}

        function setPollInterval(sec) {{
            currentPollIntervalSeconds = parseInt(sec, 10);
            if (isNaN(currentPollIntervalSeconds) || currentPollIntervalSeconds < 0) currentPollIntervalSeconds = 5;
            localStorage.setItem('tierbridge_poll_interval', currentPollIntervalSeconds);
            applyPollInterval(currentPollIntervalSeconds, true);
            closePollDropdown();
        }}

        function applyCustomPollInterval() {{
            const input = document.getElementById('customPollInput');
            if (!input) return;
            const val = parseInt(input.value, 10);
            if (!isNaN(val) && val > 0) {{
                setPollInterval(val);
            }}
        }}

        function applyPollInterval(sec, doImmediateFetch) {{
            if (livePollIntervalTimer) {{
                clearInterval(livePollIntervalTimer);
                livePollIntervalTimer = null;
            }}

            const badge = document.getElementById('liveSyncBadge');
            const toggleIcon = document.getElementById('pollToggleIcon');
            const customInput = document.getElementById('customPollInput');
            if (customInput) customInput.value = (sec > 0 && ![3,5,10,30].includes(sec)) ? sec : '';

            // Update dropdown checkmarks
            [0, 3, 5, 10, 30].forEach(p => {{
                const el = document.getElementById(`pollCheck${{p}}`);
                if (el) {{
                    if (p === sec) el.classList.remove('hidden');
                    else el.classList.add('hidden');
                }}
            }});

            if (sec > 0) {{
                if (badge) {{
                    badge.className = "flex items-center gap-1.5 bg-emerald-950/70 border border-emerald-500/50 px-2.5 py-1 rounded-lg text-emerald-400 text-xs font-bold cursor-pointer hover:bg-emerald-900/60 transition-all";
                    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span id="liveSyncBadgeText">${{sec}}s Live</span><i class="fa-solid fa-chevron-down text-[10px] text-emerald-400/70 ml-0.5"></i>`;
                }}
                if (toggleIcon) toggleIcon.className = "fa-solid fa-pause text-xs text-slate-400 hover:text-amber-300";
                livePollIntervalTimer = setInterval(fetchLiveDashboardStats, sec * 1000);
            }} else {{
                if (badge) {{
                    badge.className = "flex items-center gap-1.5 bg-slate-800/80 border border-slate-600 px-2.5 py-1 rounded-lg text-slate-400 text-xs font-bold cursor-pointer hover:bg-slate-700/60 transition-all";
                    badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-500"></span><span id="liveSyncBadgeText">수동 갱신</span><i class="fa-solid fa-chevron-down text-[10px] text-slate-400/70 ml-0.5"></i>`;
                }}
                if (toggleIcon) toggleIcon.className = "fa-solid fa-play text-xs text-emerald-400 hover:text-emerald-300";
            }}

            if (doImmediateFetch) {{
                fetchLiveDashboardStats();
            }}
        }}

        function toggleLivePolling() {{
            if (currentPollIntervalSeconds > 0) {{
                setPollInterval(0); // Pause
            }} else {{
                setPollInterval(5); // Default resume to 5s
            }}
        }}

        function togglePollDropdown(event) {{
            if (event) event.stopPropagation();
            const dd = document.getElementById('pollIntervalDropdown');
            if (dd) dd.classList.toggle('hidden');
        }}

        function closePollDropdown() {{
            const dd = document.getElementById('pollIntervalDropdown');
            if (dd) dd.classList.add('hidden');
        }}

        document.addEventListener('click', function(e) {{
            const dd = document.getElementById('pollIntervalDropdown');
            const badge = document.getElementById('liveSyncBadge');
            if (dd && !dd.classList.contains('hidden') && !dd.contains(e.target) && (!badge || !badge.contains(e.target))) {{
                dd.classList.add('hidden');
            }}
        }});

        async function triggerManualRefresh() {{
            const icon = document.getElementById('manualRefreshIcon');
            if (icon) icon.classList.add('fa-spin');
            await fetchLiveDashboardStats();
            setTimeout(() => {{
                if (icon) icon.classList.remove('fa-spin');
            }}, 600);
        }}

        function openGitPullModal() {{
            const gs = window.currentGitStatus || {{ current_branch: 'main', needs_pull: false, behind_count: 0, pending_commits: [] }};
            const modal = document.getElementById('gitPullModal');
            if (!modal) return;
            document.getElementById('gitModalBranch').innerText = gs.current_branch || 'main';
            document.getElementById('gitModalBehind').innerText = gs.needs_pull ? `${{gs.behind_count}}개 커밋 뒤처짐 (Pull 필요)` : '최신 상태 (Up to date)';
            
            const commitsListEl = document.getElementById('gitModalCommitsList');
            if (commitsListEl) {{
                if (gs.pending_commits && gs.pending_commits.length > 0) {{
                    commitsListEl.innerHTML = gs.pending_commits.map(c => `
                        <li class="py-1.5 px-2.5 bg-slate-800/60 rounded-lg text-xs font-mono text-slate-300 flex items-center gap-2 border border-slate-700/50">
                            <span class="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0"></span>
                            <span class="truncate">${{c.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}}</span>
                        </li>
                    `).join('');
                }} else {{
                    commitsListEl.innerHTML = `<li class="py-3 text-center text-xs text-slate-400 font-mono">현재 로컬 저장소가 원격 저장소(origin)와 최신 동기화 상태입니다.</li>`;
                }}
            }}
            modal.classList.remove('hidden');
        }}

        function closeGitPullModal() {{
            const modal = document.getElementById('gitPullModal');
            if (modal) modal.classList.add('hidden');
        }}

        function copyGitPullCommand() {{
            const cmd = "git pull && ./deploy.sh";
            navigator.clipboard.writeText(cmd).then(() => {{
                const btn = document.getElementById('copyGitCmdBtn');
                if (btn) {{
                    const origHtml = btn.innerHTML;
                    btn.innerHTML = `<i class="fa-solid fa-check text-emerald-300"></i> 복사 완료!`;
                    btn.className = "px-2.5 py-1 bg-emerald-600 text-white rounded-lg text-xs font-bold shadow transition-all flex items-center gap-1 cursor-pointer";
                    setTimeout(() => {{
                        btn.innerHTML = origHtml;
                        btn.className = "px-2.5 py-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold shadow transition-all flex items-center gap-1 cursor-pointer";
                    }}, 2000);
                }}
            }});
        }}

        let lastLiveSignature = '';

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
                    if (currentPollIntervalSeconds > 0) {{
                        badge.className = "flex items-center gap-1.5 bg-emerald-950/70 border border-emerald-500/50 px-2.5 py-1 rounded-lg text-emerald-400 text-xs font-bold cursor-pointer hover:bg-emerald-900/60 transition-all";
                        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span><span id="liveSyncBadgeText">${{currentPollIntervalSeconds}}s Live</span><i class="fa-solid fa-chevron-down text-[10px] text-emerald-400/70 ml-0.5"></i>`;
                    }} else {{
                        badge.className = "flex items-center gap-1.5 bg-slate-800/80 border border-slate-600 px-2.5 py-1 rounded-lg text-slate-400 text-xs font-bold cursor-pointer hover:bg-slate-700/60 transition-all";
                        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-500"></span><span id="liveSyncBadgeText">수동 갱신</span><i class="fa-solid fa-chevron-down text-[10px] text-slate-400/70 ml-0.5"></i>`;
                    }}
                }}
                const data = await res.json();
                
                if (data.git_status) {{
                    window.currentGitStatus = data.git_status;
                    const gitBadge = document.getElementById('gitStatusBadge');
                    const gitText = document.getElementById('gitStatusText');
                    if (data.git_status.needs_pull) {{
                        if (gitBadge) {{
                            gitBadge.classList.remove('hidden');
                            gitBadge.className = "flex items-center gap-1.5 bg-amber-950/80 border border-amber-500/70 px-2.5 py-1.5 rounded-xl shadow-lg text-amber-300 text-xs font-bold hover:bg-amber-900/80 transition-all cursor-pointer animate-pulse";
                            gitBadge.onclick = openGitPullModal;
                        }}
                        if (gitText) gitText.innerHTML = `<i class="fa-solid fa-arrow-down mr-1"></i>${{data.git_status.behind_count}} Pull 필요`;
                    }} else if (data.git_status.is_git) {{
                        if (gitBadge) {{
                            gitBadge.classList.remove('hidden');
                            gitBadge.className = "hidden md:flex items-center gap-1.5 bg-slate-800/80 border border-slate-700/60 px-2.5 py-1.5 rounded-xl text-slate-400 text-xs font-mono cursor-pointer hover:bg-slate-700/60 transition-all";
                            gitBadge.onclick = openGitPullModal;
                        }}
                        if (gitText) gitText.innerHTML = `<i class="fa-solid fa-check text-emerald-400 mr-1"></i>Up to date`;
                    }}
                }}

                if (data.enterprise_balance) {{
                    const eb = data.enterprise_balance;
                    const limitVal = parseFloat(eb.limit) || 0;
                    const usedVal = parseFloat(eb.used) || 0;
                    const remVal = (limitVal > 0) ? Math.max(0, limitVal - usedVal) : (parseFloat(eb.remaining) || 0);
                    
                    const usedPct = limitVal > 0 ? ((usedVal / limitVal) * 100) : 0;
                    const remPct = Math.max(0, 100 - usedPct);

                    const usedEl = document.getElementById('entUsedCredits');
                    const remEl = document.getElementById('entRemainingCredits');
                    const limEl = document.getElementById('entLimitCredits');
                    const barEl = document.getElementById('entProgressBar');
                    const resetEl = document.getElementById('entResetAt');
                    if (usedEl) usedEl.innerText = `${{usedVal.toFixed(2)}} Cr (${{usedPct.toFixed(1)}}%)`;
                    if (remEl) remEl.innerText = `${{remVal.toFixed(2)}} Cr (${{remPct.toFixed(1)}}%)`;
                    if (limEl) limEl.innerText = `${{limitVal.toFixed(2)}} Cr`;
                    if (barEl) barEl.style.width = `${{Math.min(100, Math.max(0, usedPct))}}%`;
                    if (resetEl && eb.reset_at) {{
                        const d = new Date(eb.reset_at * 1000);
                        resetEl.innerText = `${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}-${{String(d.getDate()).padStart(2,'0')}}`;
                    }}
                }}

                const recordsLen = (data.records || []).length;
                const lastRec = recordsLen > 0 ? data.records[recordsLen - 1] : {{}};
                const newSig = `${{recordsLen}}:${{lastRec.timestamp || ''}}:${{lastRec.cost || 0}}:${{(data.healing_history || []).length}}`;

                if (newSig !== lastLiveSignature) {{
                    lastLiveSignature = newSig;
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
                    if (data.memory_stats) {{
                        currentMemStats = data.memory_stats;
                    }}
                    const currentMonth = document.getElementById('monthSelect').value;
                    const currentSession = document.getElementById('sessionSelect').value;
                    renderDashboard(currentMonth, currentSession);
                }}

                try {{
                    let memRes = await fetch('http://127.0.0.1:18080/v1/dashboard/memories');
                    if (memRes.ok) {{
                        const memData = await memRes.json();
                        if (memData.memories) {{
                            currentMemories = memData.memories;
                        }}
                    }}
                    let nodeSetChanged = false;
                    let graphRes = await fetch('http://127.0.0.1:18080/v1/dashboard/memories/graph');
                    if (graphRes.ok) {{
                        const gData = await graphRes.json();
                        if (gData.nodes) {{
                            const oldIds = (currentGraphData.nodes || []).map(n => n.id).sort().join(',');
                            const newIds = gData.nodes.map(n => n.id).sort().join(',');
                            if (oldIds !== newIds) {{
                                nodeSetChanged = true;
                            }}
                            currentGraphData = gData;
                        }}
                    }}
                    let edgeRes = await fetch('http://127.0.0.1:18080/v1/dashboard/memories/top-edges');
                    if (edgeRes.ok) {{
                        const eData = await edgeRes.json();
                        if (eData.edges) {{
                            currentTopEdges = eData.edges;
                        }}
                    }}
                    if (currentDashboardTab === 'memory') {{
                        renderMemoryView(currentMemories, currentMemStats, currentGraphData, currentTopEdges);
                        if (nodeSetChanged) {{
                            initMemoryGraph(currentGraphData);
                            const expModal = document.getElementById('expandedGraphModal');
                            if (expModal && !expModal.classList.contains('hidden')) {{
                                if (currentModalViewMode === 'network') {{
                                    initExpandedMemoryGraph(currentGraphData);
                                }} else {{
                                    initMarkmapTree();
                                }}
                            }}
                        }}
                    }}
                }} catch(me) {{ }}
            }} else {{
                if (badge) {{
                    badge.className = "flex items-center gap-1.5 bg-rose-950/80 border border-rose-500/60 px-2.5 py-1 rounded-lg text-rose-400 text-xs font-bold cursor-pointer hover:bg-rose-900/60 transition-all";
                    badge.innerHTML = '<span class="w-2 h-2 rounded-full bg-rose-400 animate-ping"></span><span id="liveSyncBadgeText">Disconnected</span><i class="fa-solid fa-chevron-down text-[10px] text-rose-400/70 ml-0.5"></i>';
                }}
            }}
        }}

        window.onload = function() {{
            applyTheme(currentTheme);
            initVersionSelector();
            renderHealingHistory(healingHistoryData);
            renderMemoryView(currentMemories, currentMemStats, currentGraphData, currentTopEdges);
            const initialMonth = document.getElementById('monthSelect').value;
            const initialSession = document.getElementById('sessionSelect').value;
            renderDashboard(initialMonth, initialSession);
            initPollInterval();
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
        r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?(?:\[sid:\s*(?P<sid>[^\]]+)\]\s*)?➔ \[USAGE(?::\s*(?P<decision_opt>[^\]]+))?\](?:\s+(?P<decision_legacy>[^\s(]+))?\s+\((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| real_credit=(?P<real_credit>[\d\.]+))?(?: \| balance=(?P<balance>[\d\.]+))?(?: \| loc=(?P<loc>\d+) lines)? \| cost=\$(?P<cost>[\d\.]+) USD'
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
                
                decision_str = u_match.group("decision_opt") or u_match.group("decision_legacy") or "UNKNOWN"
                model = u_match.group("model")
                in_tok = int(u_match.group("in_tok"))
                out_tok = int(u_match.group("out_tok"))
                loc_val = int(u_match.group("loc")) if u_match.group("loc") else 0
                cost = float(u_match.group("cost"))
                real_credit_val = float(u_match.group("real_credit")) if u_match.group("real_credit") else None
                balance_val = float(u_match.group("balance")) if u_match.group("balance") else None
                credits_val = real_credit_val if real_credit_val is not None else (cost / 0.20)

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
                    "timestamp": ts_str or (dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "N/A"),
                    "datetime": dt,
                    "date": date_key,
                    "month": month_key,
                    "session_id": sid_str,
                    "decision": decision_str,
                    "model": model,
                    "prompt": associated_prompt,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": in_tok + out_tok,
                    "loc": loc_val,
                    "cost": cost,
                    "real_credit": real_credit_val,
                    "balance": balance_val,
                    "credits": credits_val
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
        if args.html:
            print("ℹ️  [USAGE] 누적 로그가 아직 없습니다. 초기 대시보드를 생성하여 표시합니다.")
            generate_html_dashboard(
                all_raw_records=[],
                records=[],
                daily_stats=defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0}),
                monthly_stats=defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0}),
                session_stats=defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0}),
                decision_stats=defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0}),
                prompt_stats=defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0, "credits": 0.0, "prompt": "", "decision": "", "session_id": ""}),
                total_cost=0.0,
                total_credits=0.0,
                total_tokens=0,
                total_loc=0,
                target_date=target_date,
                target_month=target_month,
                target_session=target_session,
                healing_history=[]
            )
            if not args.no_open:
                html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_dashboard.html")
                webbrowser.open(f"file://{html_path}")
            return
        else:
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
    total_credits = sum(r.get("credits", r["cost"] / 0.20) for r in records)

    decision_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0})
    daily_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0})
    monthly_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0})
    session_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "loc": 0, "cost": 0.0, "credits": 0.0})
    prompt_stats = defaultdict(lambda: {"count": 0, "in_tok": 0, "out_tok": 0, "cost": 0.0, "credits": 0.0, "prompt": "", "decision": "", "session_id": ""})

    for r in records:
        d = r["decision"]
        dt_key = r["date"]
        m_key = r["month"]
        s_key = r["session_id"]
        p_key = r["prompt"] if r["prompt"] else "(서브 스텝 / 연속 릴레이)"
        
        c_val = r.get("credits", r["cost"] / 0.20)

        decision_stats[d]["count"] += 1
        decision_stats[d]["in_tok"] += r["input_tokens"]
        decision_stats[d]["out_tok"] += r["output_tokens"]
        decision_stats[d]["loc"] += r["loc"]
        decision_stats[d]["cost"] += r["cost"]
        decision_stats[d]["credits"] += c_val

        daily_stats[dt_key]["count"] += 1
        daily_stats[dt_key]["in_tok"] += r["input_tokens"]
        daily_stats[dt_key]["out_tok"] += r["output_tokens"]
        daily_stats[dt_key]["loc"] += r["loc"]
        daily_stats[dt_key]["cost"] += r["cost"]
        daily_stats[dt_key]["credits"] += c_val

        monthly_stats[m_key]["count"] += 1
        monthly_stats[m_key]["in_tok"] += r["input_tokens"]
        monthly_stats[m_key]["out_tok"] += r["output_tokens"]
        monthly_stats[m_key]["loc"] += r["loc"]
        monthly_stats[m_key]["cost"] += r["cost"]
        monthly_stats[m_key]["credits"] += c_val

        session_stats[s_key]["count"] += 1
        session_stats[s_key]["in_tok"] += r["input_tokens"]
        session_stats[s_key]["out_tok"] += r["output_tokens"]
        session_stats[s_key]["loc"] += r["loc"]
        session_stats[s_key]["cost"] += r["cost"]
        session_stats[s_key]["credits"] += c_val

        if d != "CLASSIFIER" or not prompt_stats[p_key]["decision"]:
            prompt_stats[p_key]["decision"] = d
        if d != "CLASSIFIER":
            prompt_stats[p_key]["count"] += 1
        prompt_stats[p_key]["in_tok"] += r["input_tokens"]
        prompt_stats[p_key]["out_tok"] += r["output_tokens"]
        prompt_stats[p_key]["cost"] += r["cost"]
        prompt_stats[p_key]["credits"] += c_val
        prompt_stats[p_key]["prompt"] = p_key
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
        credits = s.get('credits', s['cost'] / 0.20)
        print(f"{dec:<18} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[2] 🗓️  일자(Daily)별 소모 요약")
    print(f"{'날짜':<12} | {'요청 수':<8} | {'Input 토큰':<12} | {'Output 토큰':<12} | {'코드 (LOC)':<10} | {'비용 (USD)':<12} | {'예상 크레딧 (Credits)':<20}")
    print("-" * 95)
    for date_str, s in sorted(daily_stats.items()):
        credits = s.get('credits', s['cost'] / 0.20)
        print(f"{date_str:<12} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[3] 🗓️  월별(Monthly) 소모 요약")
    print(f"{'년-월':<12} | {'요청 수':<8} | {'Input 토큰':<12} | {'Output 토큰':<12} | {'코드 (LOC)':<10} | {'비용 (USD)':<12} | {'예상 크레딧 (Credits)':<20}")
    print("-" * 95)
    for month_str, s in sorted(monthly_stats.items()):
        credits = s.get('credits', s['cost'] / 0.20)
        print(f"{month_str:<12} | {s['count']:<8,} | {s['in_tok']:<12,} | {s['out_tok']:<12,} | {s['loc']:<10,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[4] 🔀 세션(Session ID)별 소모 요약 (Top 10)")
    print(f"{'Session ID':<38} | {'요청 수':<8} | {'소모 토큰':<12} | {'비용 (USD)':<12} | {'소모 크레딧 (Credits)'}")
    print("-" * 95)
    top_sessions = sorted(session_stats.items(), key=lambda x: x[1]["cost"], reverse=True)[:10]
    for sid, s in top_sessions:
        credits = s.get('credits', s['cost'] / 0.20)
        tok_total = s['in_tok'] + s['out_tok']
        print(f"{sid:<38} | {s['count']:<8,} | {tok_total:<12,} | ${s['cost']:.6f}   | {credits:.2f} Credits")

    print("\n[5] 💡 Top 크레딧 소모 프롬프트 턴 인사이트 (Top Prompt Insights)")
    print(f"{'Rank':<4} | {'소모 크레딧':<12} | {'소모 토큰':<10} | {'등급':<14} | {'프롬프트 요약'}")
    print("-" * 95)
    top_p = sorted(prompt_stats.values(), key=lambda x: x["cost"], reverse=True)[:5]
    for idx, p in enumerate(top_p, 1):
        c_val = p.get("credits", p["cost"] / 0.20)
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
    if args.balance:
        show_enterprise_balance()
    else:
        analyze(args.log_file, target_date=args.date, target_month=args.month, target_session=args.session, generate_html=args.html, open_browser=not args.no_open)
