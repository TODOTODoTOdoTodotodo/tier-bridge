# src/harnex/orchestrator/cli.py
import argparse
import json
import os
import sys
import uuid
import httpx

from harnex.orchestrator.models import TaskDAG, SubTask, TaskState


def get_base_url() -> str:
    return "http://127.0.0.1:18080/v1/orchestrator"


def cmd_list(args):
    url = f"{get_base_url()}/tasks"
    try:
        resp = httpx.get(url, timeout=5.0)
        data = resp.json()
        tasks = data.get("tasks", [])
        if not tasks:
            print("📭 현재 등록된 멀티에이전트 태스크가 없습니다.")
            return

        print("=" * 80)
        print("🧩 [Harnex Orchestrator] 활성 및 완료 태스크 목록")
        print("=" * 80)
        for t in tasks:
            print(f"• ID: {t['task_id']} | 상태: [{t['state']}] | 진행: {t['completed_subtasks']}/{t['total_subtasks']} subtasks")
            print(f"  제목: {t['title']}")
            for s in t.get("subtasks", []):
                print(f"    - [{s['state']}] {s['subtask_id']} ({s['tier']}): {s['title']} (LOC: +{s['loc']}, Cr: {s['credits']:.4f})")
            print("-" * 80)
    except Exception as e:
        print(f"❌ 하네스 오케스트레이터 연결 실패: {e}")


def cmd_dispatch(args):
    dag_id = f"dag_{uuid.uuid4().hex[:8]}"
    subtasks = {}

    if args.subtasks:
        for idx, item in enumerate(args.subtasks):
            parts = item.split(":", 1)
            title = parts[0].strip()
            instruction = parts[1].strip() if len(parts) > 1 else title
            sid = f"sub_{idx + 1}"
            subtasks[sid] = SubTask(
                subtask_id=sid,
                parent_task_id=dag_id,
                title=title,
                instruction=instruction,
                assigned_tier=args.tier or "SILVER"
            )
    else:
        # Single subtask from title
        sid = "sub_1"
        subtasks[sid] = SubTask(
            subtask_id=sid,
            parent_task_id=dag_id,
            title=args.title,
            instruction=args.title,
            assigned_tier=args.tier or "SILVER"
        )

    target_repo = getattr(args, "repo", None) or os.getcwd()

    dag = TaskDAG(
        dag_id=dag_id,
        title=args.title,
        target_repo=target_repo,
        subtasks=subtasks
    )

    url = f"{get_base_url()}/dispatch"
    payload = dag.model_dump() if hasattr(dag, "model_dump") else dag.dict()
    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            print(f"🚀 [디스패치 성공] TaskDAG '{dag_id}' 가 등록되어 백그라운드 워커가 가동되었습니다!")
            print(f"   • 제목: {args.title}")
            print(f"   • 서브태스크: {len(subtasks)}개")
            print(f"   • 실시간 진행 조회: harnex-task status {dag_id}")
        else:
            print(f"❌ 디스패치 실패 (Status {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ 하네스 오케스트레이터 요청 오류: {e}")


def cmd_status(args):
    url = f"{get_base_url()}/tasks/{args.dag_id}"
    try:
        resp = httpx.get(url, timeout=5.0)
        if resp.status_code == 404:
            print(f"❌ TaskDAG '{args.dag_id}'를 찾을 수 없습니다.")
            return
        data = resp.json()
        print("=" * 80)
        print(f"🌳 [Tree-of-Thought DAG] {data['dag_id']} [{data['state']}]")
        print(f"목표: {data['title']}")
        print(f"생성 일시: {data['created_at']}")
        if data.get("completed_at"):
            print(f"완료 일시: {data['completed_at']}")
        print("-" * 80)
        subtasks = list(data.get("subtasks", {}).items())
        for idx, (sid, s) in enumerate(subtasks):
            is_last = (idx == len(subtasks) - 1)
            branch = "└──" if is_last else "├──"
            pipe = "   " if is_last else "│  "
            presence = s.get("presence") or s.get("state") or "READY"
            icon = "🟢" if presence == "READY" else ("🔵" if presence == "THINKING" else ("🟡" if presence in ("CODING", "RUNNING") else ("⚪" if presence == "COMPLETED" else "🔴")))
            
            print(f"{branch} 🌿 [{sid}] {s.get('title', sid)} (티어: {s['assigned_tier']}) [{icon} {presence}]")
            print(f"{pipe} ├── 📋 지시: {s['instruction']}")
            
            # 주입된 사내 장기기억 표시
            mems = s.get("injected_memories") or []
            if mems:
                for m in mems:
                    print(f"{pipe} ├── 🧠 주입된 기억: 📌 {m.get('title')} ({int(m.get('score', 0.85) * 100)}%)")
            
            pid_str = f"PID: {s['worker_pid']}" if s.get("worker_pid") else "PID: N/A"
            loc_str = f"+{s.get('loc_modified', 0)} lines"
            cr_str = f"{s.get('credits_used', 0.0):.4f} Cr"
            print(f"{pipe} └── 💳 {pid_str} | 코드: {loc_str} | 소모: {cr_str}")
            if s.get("error_message"):
                print(f"{pipe}     ⚠️ 오류 메시지: {s['error_message']}")
        print("=" * 80)
    except Exception as e:
        print(f"❌ 상태 조회 실패: {e}")


def cmd_watch(args):
    dag_id = args.dag_id
    url = f"{get_base_url()}/tasks/{dag_id}/events"
    print("=" * 80)
    print(f"🔭 [Harnex Watcher] TaskDAG '{dag_id}' 실시간 에이전트 관제 스트림 시작 (종료: Ctrl+C)")
    print("=" * 80)

    seen_ids = set()
    import time
    try:
        while True:
            try:
                resp = httpx.get(url, timeout=4.0)
                if resp.status_code == 200:
                    data = resp.json()
                    activities = data.get("activities", [])
                    for act in activities:
                        aid = act.get("id")
                        if aid not in seen_ids:
                            seen_ids.add(aid)
                            ts = (act.get("timestamp") or "")[11:19]
                            act_type = act.get("activity_type", "LOG")
                            sub = act.get("subtask_id", "DAG")
                            tier = act.get("tier", "SILVER")
                            msg = act.get("message", "")
                            
                            badge_color = "\033[36m" # cyan
                            if act_type == "MEMORY":
                                badge_color = "\033[35m" # purple
                            elif act_type == "THOUGHT":
                                badge_color = "\033[34m" # blue
                            elif act_type == "USER_CHAT":
                                badge_color = "\033[32m" # green
                            elif act_type == "ACTION":
                                badge_color = "\033[33m" # yellow
                            
                            reset_color = "\033[0m"
                            print(f"[{ts}] {badge_color}[{act_type}]{reset_color} \033[1m{sub} ({tier})\033[0m: {msg}")
            except Exception:
                pass
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n👋 관제 스트림을 종료합니다.")


def cmd_chat(args):
    dag_id = args.dag_id
    url = f"{get_base_url()}/tasks/{dag_id}/chat"
    print("=" * 80)
    print(f"💬 [Harnex Interactive Mission Control] TaskDAG '{dag_id}' 에이전트 대화형 콘솔")
    print("특정 워커 멘션 가능: '@sub_1 Lombok 어노테이션 유지해줘' (종료: exit / quit)")
    print("=" * 80)

    while True:
        try:
            line = input(f"({dag_id}) ❯ ").strip()
            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                print("👋 대화형 콘솔을 종료합니다.")
                break

            payload = {"message": line}
            resp = httpx.post(url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                target = data.get("target_subtask_id") or "ALL"
                print(f"   ↳ ✅ [전달 완료] ➔ 대상: {target} | 메시지: {data.get('message')}")
            else:
                print(f"   ↳ ❌ 전달 실패 ({resp.status_code}): {resp.text}")
        except KeyboardInterrupt:
            print("\n👋 대화형 콘솔을 종료합니다.")
            break
        except Exception as e:
            print(f"   ↳ ❌ 통신 오류: {e}")


def main():
    parser = argparse.ArgumentParser(description="Harnex Task Orchestrator CLI")
    subparsers = parser.add_subparsers(dest="command")

    # list
    subparsers.add_parser("list", help="List all task DAGs")

    # dispatch
    p_disp = subparsers.add_parser("dispatch", help="Dispatch a new task DAG")
    p_disp.add_argument("title", help="Overall task title or main instruction")
    p_disp.add_argument("-s", "--subtasks", action="append", help="Subtask format: 'Title: Instruction'")
    p_disp.add_argument("-t", "--tier", default="SILVER", help="Default model tier (BRONZE, SILVER, GOLD, PLATINUM)")
    p_disp.add_argument("-r", "--repo", default=None, help="Target repository directory (default: current working directory)")

    # status
    p_stat = subparsers.add_parser("status", help="Get status of a specific task DAG")
    p_stat.add_argument("dag_id", help="DAG ID")

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch live agent stream for a task DAG")
    p_watch.add_argument("dag_id", help="DAG ID")

    # chat
    p_chat = subparsers.add_parser("chat", help="Interactive chat / instruction injection for a task DAG")
    p_chat.add_argument("dag_id", help="DAG ID")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "dispatch":
        cmd_dispatch(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "watch":
        cmd_watch(args)
    elif args.command == "chat":
        cmd_chat(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
