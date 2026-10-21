# src/harnex/orchestrator/cli.py
import argparse
import json
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

    dag = TaskDAG(
        dag_id=dag_id,
        title=args.title,
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
        print(f"🧩 태스크 상세 정보: {data['dag_id']} [{data['state']}]")
        print(f"제목: {data['title']}")
        print(f"생성 일시: {data['created_at']}")
        if data.get("completed_at"):
            print(f"완료 일시: {data['completed_at']}")
        print("-" * 80)
        for sid, s in data.get("subtasks", {}).items():
            print(f"• 서브태스크 [{s['state']}] {sid} (티어: {s['assigned_tier']})")
            print(f"  지시: {s['instruction']}")
            if s.get("worker_pid"):
                print(f"  워커 PID: {s['worker_pid']} | 격리 경로: {s.get('worktree_path')}")
            if s.get("loc_modified"):
                print(f"  생성 코드: +{s['loc_modified']} lines | 소모 크레딧: {s.get('credits_used', 0.0):.4f} Cr")
            if s.get("error_message"):
                print(f"  ⚠️ 오류 메시지: {s['error_message']}")
        print("=" * 80)
    except Exception as e:
        print(f"❌ 상태 조회 실패: {e}")


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

    # status
    p_stat = subparsers.add_parser("status", help="Get status of a specific task DAG")
    p_stat.add_argument("dag_id", help="DAG ID")

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "dispatch":
        cmd_dispatch(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
