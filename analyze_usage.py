#!/usr/bin/env python3
import sys
import os
import re
import argparse
from collections import defaultdict
from datetime import datetime

def parse_args():
    parser = argparse.ArgumentParser(description="TierBridge 로그 기반 USAGE 통계 분석기")
    parser.add_argument("log_file", nargs="?", default="harness.log", help="분석할 로그 파일 경로 (기본: harness.log)")
    parser.add_argument("--date", "-d", type=str, help="특정 날짜 필터 (형식: YYYY-MM-DD)")
    return parser.parse_args()

def analyze(log_filepath, target_date=None):
    if not os.path.exists(log_filepath):
        print(f"❌ Error: 로그 파일을 찾을 수 없습니다: {log_filepath}")
        sys.exit(1)

    # 패턴 예시:
    # [2026-07-27 10:46:15] ➔ [USAGE] LUNA:LOW (gpt-5.6-luna) | input=21 output=381 tokens | loc=42 lines | cost=$0.001164 USD
    # ➔ [USAGE] LUNA:LOW (gpt-5.6-luna) | input=21 output=381 tokens | cost=$0.001164 USD  (구형 로그 호환)
    usage_pattern = re.compile(
        r'^(?:\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*)?➔ \[USAGE\] (?P<decision>[^\s]+) \((?P<model>[^)]+)\) \| input=(?P<in_tok>\d+) output=(?P<out_tok>\d+) tokens(?: \| loc=(?P<loc>\d+) lines)? \| cost=\$(?P<cost>[\d\.]+) USD'
    )

    records = []
    with open(log_filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            match = usage_pattern.search(line)
            if match:
                ts_str = match.group("timestamp")
                dt = None
                date_key = "Unknown Date"
                if ts_str:
                    try:
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        date_key = dt.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                
                # 날짜 필터링 적용
                if target_date and date_key != target_date:
                    continue

                decision = match.group("decision")
                model = match.group("model")
                in_tok = int(match.group("in_tok"))
                out_tok = int(match.group("out_tok"))
                loc_val = int(match.group("loc")) if match.group("loc") else 0
                cost = float(match.group("cost"))

                records.append({
                    "datetime": dt,
                    "date": date_key,
                    "decision": decision,
                    "model": model,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "total_tokens": in_tok + out_tok,
                    "loc": loc_val,
                    "cost": cost
                })

    if not records:
        filter_msg = f" (날짜: {target_date})" if target_date else ""
        print(f"⚠️  분석할 [USAGE] 로그 레코드가 없습니다.{filter_msg}")
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

    for r in records:
        d = r["decision"]
        dt_key = r["date"]
        
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

    print("\n====================================================================================================")
    print("📊 [TierBridge 로그 기반 USAGE 사용량 및 소스코드 작성(LOC) 통계 보고서]")
    print("====================================================================================================")
    if target_date:
        print(f"🗓️  조회 대상 날짜: {target_date}")
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
    print("====================================================================================================\n")

if __name__ == "__main__":
    args = parse_args()
    analyze(args.log_file, args.date)
