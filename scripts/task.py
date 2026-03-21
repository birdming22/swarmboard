#!/usr/bin/env python3
"""
Task tracking system for SwarmBoard agents.
Allows agents to create, update, and query task status.

Usage:
  python scripts/task.py create --title "Update SKILL.md" --assignee sisyphus --priority high
  python scripts/task.py update --id task-001 --status in_progress
  python scripts/task.py list
  python scripts/task.py list --status in_progress
"""

import argparse
import json
import os
import sys
from datetime import datetime


TASKS_FILE = "data/tasks.json"


def load_tasks():
    """Load tasks from JSON file."""
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r") as f:
            return json.load(f)
    return []


def save_tasks(tasks):
    """Save tasks to JSON file."""
    os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)


def generate_task_id(tasks):
    """Generate a unique task ID."""
    return f"task-{len(tasks) + 1:03d}"


def create_task(title, assignee, priority="medium"):
    """Create a new task."""
    tasks = load_tasks()

    task = {
        "id": generate_task_id(tasks),
        "title": title,
        "assignee": assignee,
        "priority": priority,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    tasks.append(task)
    save_tasks(tasks)

    print(f"[task] Created: {task['id']} - {title}")
    return task


def update_task(task_id, status):
    """Update task status."""
    tasks = load_tasks()

    for task in tasks:
        if task["id"] == task_id:
            task["status"] = status
            task["updated_at"] = datetime.now().isoformat()
            save_tasks(tasks)
            print(f"[task] Updated: {task_id} -> {status}")
            return task

    print(f"[task] Error: Task {task_id} not found", file=sys.stderr)
    return None


def list_tasks(status=None):
    """List tasks, optionally filtered by status."""
    tasks = load_tasks()

    if status:
        tasks = [t for t in tasks if t["status"] == status]

    if not tasks:
        print("[task] No tasks found")
        return

    for task in tasks:
        status_icon = {
            "pending": "⏳",
            "in_progress": "🔄",
            "completed": "✅",
            "blocked": "🚫",
        }.get(task["status"], "❓")

        print(f"{status_icon} {task['id']}: {task['title']}")
        print(f"   Assignee: {task['assignee']}")
        print(f"   Priority: {task['priority']}")
        print(f"   Status: {task['status']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Task tracking system")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    create_parser = subparsers.add_parser("create", help="Create a new task")
    create_parser.add_argument("--title", required=True, help="Task title")
    create_parser.add_argument("--assignee", required=True, help="Assignee name")
    create_parser.add_argument(
        "--priority",
        default="medium",
        choices=["low", "medium", "high"],
        help="Task priority",
    )

    update_parser = subparsers.add_parser("update", help="Update task status")
    update_parser.add_argument("--id", required=True, help="Task ID")
    update_parser.add_argument(
        "--status",
        required=True,
        choices=["pending", "in_progress", "completed", "blocked"],
        help="New status",
    )

    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument(
        "--status",
        choices=["pending", "in_progress", "completed", "blocked"],
        help="Filter by status",
    )

    args = parser.parse_args()

    if args.command == "create":
        create_task(args.title, args.assignee, args.priority)
    elif args.command == "update":
        update_task(args.id, args.status)
    elif args.command == "list":
        list_tasks(args.status)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
