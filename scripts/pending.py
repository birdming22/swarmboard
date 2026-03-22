#!/usr/bin/env python3
"""
Pending message queue for SwarmBoard.
Allows daemon to write messages to a queue for later processing by agents.

Usage:
  python scripts/pending.py add --message '{"msg_id": "...", ...}'
  python scripts/pending.py list
  python scripts/pending.py process --model <model-name>
  python scripts/pending.py clear
"""

import argparse
import json
import os
import sys
from datetime import datetime

PENDING_FILE = "data/pending.json"


def load_pending():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_pending(messages):
    os.makedirs(os.path.dirname(PENDING_FILE), exist_ok=True)
    with open(PENDING_FILE, "w") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)


def add_message(message_str):
    messages = load_pending()
    try:
        message = json.loads(message_str)
        message["queued_at"] = datetime.now().isoformat()
        messages.append(message)
        save_pending(messages)
        print(f"[pending] Added message: {message.get('msg_id', 'unknown')}")
    except json.JSONDecodeError as e:
        print(f"[pending] Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)


def list_messages():
    messages = load_pending()
    if not messages:
        print("[pending] No pending messages")
        return

    print(f"[pending] {len(messages)} pending messages:")
    for i, msg in enumerate(messages):
        source = msg.get("source", {}).get("model_name", "unknown")
        content = msg.get("content", "")[:50]
        queued_at = msg.get("queued_at", "unknown")
        print(f"  {i + 1}. [{source}] {content}... (queued: {queued_at})")


def process_messages(model_name):
    messages = load_pending()
    if not messages:
        print("[pending] No pending messages to process")
        return []

    model_msgs = []
    other_msgs = []

    for msg in messages:
        content = msg.get("content", "")
        if f"@{model_name}" in content or "@all" in content:
            model_msgs.append(msg)
        else:
            other_msgs.append(msg)

    if model_msgs:
        print(f"[pending] Processing {len(model_msgs)} messages for {model_name}")
        for msg in model_msgs:
            print(json.dumps(msg, ensure_ascii=False))
    else:
        print(f"[pending] No messages for @{model_name}")

    save_pending(other_msgs)
    return model_msgs


def clear_messages():
    save_pending([])
    print("[pending] Cleared all pending messages")


def main():
    parser = argparse.ArgumentParser(description="Pending message queue for SwarmBoard")
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a message to the queue")
    add_parser.add_argument("--message", required=True, help="JSON message to add")

    subparsers.add_parser("list", help="List pending messages")

    process_parser = subparsers.add_parser(
        "process", help="Process messages for a model"
    )
    process_parser.add_argument("--model", required=True, help="Model name to filter")

    subparsers.add_parser("clear", help="Clear all pending messages")

    args = parser.parse_args()

    if args.command == "add":
        add_message(args.message)
    elif args.command == "list":
        list_messages()
    elif args.command == "process":
        process_messages(args.model)
    elif args.command == "clear":
        clear_messages()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
