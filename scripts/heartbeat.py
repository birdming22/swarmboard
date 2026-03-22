#!/usr/bin/env python3
"""
Heartbeat script for SwarmBoard agents.
Updates status file periodically so other agents know who's online.

Usage:
  python scripts/heartbeat.py --model <model-name> [--interval 30] [--status listening]
"""

import argparse
import json
import os
import sys
import time

STATUS_FILE = "data/status.json"


def load_status():
    """Load status file or create empty dict."""
    if os.path.exists(STATUS_FILE):
        try:
            with open(STATUS_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"agents": {}}


def save_status(status):
    """Save status to file."""
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)


def update_heartbeat(model_name, status, instance_id):
    """Update heartbeat for an agent."""
    data = load_status()
    data["agents"][model_name] = {
        "status": status,
        "last_heartbeat": int(time.time()),
        "instance_id": instance_id,
    }
    save_status(data)


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard agent heartbeat")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument(
        "--status",
        default="listening",
        choices=["listening", "busy", "offline"],
        help="Agent status",
    )
    parser.add_argument(
        "--interval", type=int, default=30, help="Heartbeat interval in seconds"
    )
    parser.add_argument(
        "--once", action="store_true", help="Send one heartbeat and exit"
    )
    args = parser.parse_args()

    instance_id = f"{args.model}-{os.getpid()}"

    print(
        f"[heartbeat] Starting for {args.model} (status: {args.status}, interval: {args.interval}s)"
    )

    try:
        while True:
            update_heartbeat(args.model, args.status, instance_id)
            print(f"[heartbeat] Updated {args.model}: {args.status}")
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        update_heartbeat(args.model, "offline", instance_id)
        print(f"\n[heartbeat] {args.model} set to offline")


if __name__ == "__main__":
    main()
