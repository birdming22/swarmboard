#!/usr/bin/env python3
"""
Confirmation message helper for SwarmBoard agents.
Sends confirmation, progress, and completion messages to the blackboard.

Usage:
  python scripts/confirm.py --model <model-name> --status received --task "正在更新 SKILL.md"
  python scripts/confirm.py --model <model-name> --status progress --task "已處理 50%"
  python scripts/confirm.py --model <model-name> --status done --task "已更新 SKILL.md"
"""

import argparse
import subprocess
import sys


def send_confirmation(model, status, task):
    """Send confirmation message to blackboard."""
    agent_name = model.split("/")[-1] if "/" in model else model

    if status == "received":
        message = f"@Commander 收到！我是 {agent_name}，正在處理 {task}..."
    elif status == "progress":
        message = f"@Commander 進度更新！我是 {agent_name}，{task}"
    elif status == "done":
        message = f"@Commander 完成！我是 {agent_name}，{task}"
    elif status == "error":
        message = f"@Commander 錯誤！我是 {agent_name}，{task}"
    else:
        message = f"@Commander 狀態更新：{status}，我是 {agent_name}，{task}"

    result = subprocess.run(
        [sys.executable, "scripts/send.py", message, "--model", model],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode == 0:
        print(f"[confirm] Sent: {message}")
    else:
        print(f"[confirm] Error: {result.stderr}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Send confirmation messages")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument(
        "--status",
        required=True,
        choices=["received", "progress", "done", "error"],
        help="Confirmation status",
    )
    parser.add_argument("--task", required=True, help="Task description")
    args = parser.parse_args()

    send_confirmation(args.model, args.status, args.task)


if __name__ == "__main__":
    main()
