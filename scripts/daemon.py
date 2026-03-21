#!/usr/bin/env python3
"""
Persistent monitoring daemon for SwarmBoard.
Continuously checks for new messages and prints them to stdout.

Usage:
  python scripts/daemon.py --model <model-name> [--interval 5] [--max-rounds 100] [--mention-filter]

The daemon will:
1. Read the blackboard to get the initial last message ID
2. Enter a loop, checking for new messages every <interval> seconds
3. Print new messages to stdout (one JSON per line)
4. Stop after <max-rounds> consecutive rounds with no new messages

With --mention-filter, only messages containing @<model-name> or @all are printed.

This allows agents to run the daemon and process messages as they arrive.
"""

import argparse
import json
import subprocess
import sys
import time

MAX_RETRIES = 3
RETRY_DELAY = 2


def read_blackboard():
    """Read all messages from the blackboard with retry."""
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                [sys.executable, "scripts/read.py"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return json.loads(result.stdout)
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            if attempt < MAX_RETRIES - 1:
                print(
                    f"[daemon] Read failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY)
            else:
                return []


def check_new_messages(last_id, exclude_self):
    """Check for new messages using check.py with retry."""
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/check.py",
                    "--last-id",
                    last_id,
                    "--exclude-self",
                    exclude_self,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            stdout = result.stdout.strip()

            if "NO_NEW_MESSAGES" in stdout or "TIMEOUT" in stdout or not stdout:
                return []

            # Parse NEW_MESSAGES lines
            messages = []
            for line in stdout.split("\n"):
                line = line.strip()
                if line and line != "NEW_MESSAGES":
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return messages
        except subprocess.TimeoutExpired as e:
            if attempt < MAX_RETRIES - 1:
                print(
                    f"[daemon] Check failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY)
            else:
                return []


def should_process_message(message, model_name):
    content = message.get("content", "")
    return f"@{model_name}" in content or "@all" in content


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard monitoring daemon")
    parser.add_argument("--model", required=True, help="Model name to exclude (self)")
    parser.add_argument(
        "--interval", type=int, default=5, help="Check interval in seconds (default: 5)"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=100,
        help="Max idle rounds before stopping (default: 100, use --forever to ignore)",
    )
    parser.add_argument(
        "--forever",
        action="store_true",
        help="Run forever, never stop due to idle rounds",
    )
    parser.add_argument(
        "--heartbeat",
        type=int,
        default=0,
        help="Send heartbeat status every N seconds (0=disabled)",
    )
    parser.add_argument(
        "--mention-filter",
        action="store_true",
        help="Only output messages that mention @<model-name> or @all",
    )
    args = parser.parse_args()

    # Get initial state
    all_msgs = read_blackboard()
    if not all_msgs:
        print("[daemon] Error: Could not read blackboard", file=sys.stderr)
        sys.exit(1)

    last_id = all_msgs[-1]["msg_id"]
    print(f"[daemon] Started monitoring for {args.model}", file=sys.stderr)
    print(f"[daemon] Initial last_id: {last_id}", file=sys.stderr)
    print(
        f"[daemon] Check interval: {args.interval}s, Max idle rounds: {args.max_rounds if not args.forever else 'forever'}, Heartbeat: {args.heartbeat}s",
        file=sys.stderr,
    )

    idle_rounds = 0
    total_messages = 0
    last_heartbeat = 0

    def send_heartbeat():
        """Send a heartbeat status update."""
        try:
            subprocess.run(
                [
                    sys.executable,
                    "scripts/status.py",
                    "--status",
                    "listening",
                    "--model",
                    args.model,
                ],
                capture_output=True,
                timeout=5,
            )
            print(f"[daemon] Heartbeat sent", file=sys.stderr)
        except Exception as e:
            print(f"[daemon] Heartbeat failed: {e}", file=sys.stderr)

    # Send initial heartbeat if enabled
    if args.heartbeat > 0:
        send_heartbeat()
        last_heartbeat = time.time()

    try:
        while args.forever or idle_rounds < args.max_rounds:
            new_msgs = check_new_messages(last_id, args.model)

            if new_msgs:
                idle_rounds = 0
                total_messages += len(new_msgs)
                last_id = new_msgs[-1]["msg_id"]
                print(
                    f"[daemon] Round: {len(new_msgs)} new messages (total: {total_messages})",
                    file=sys.stderr,
                )

                for msg in new_msgs:
                    if args.mention_filter and not should_process_message(
                        msg, args.model
                    ):
                        continue
                    print(json.dumps(msg, ensure_ascii=False))
                    sys.stdout.flush()
            else:
                idle_rounds += 1
                if idle_rounds % 10 == 0:
                    print(
                        f"[daemon] Idle round {idle_rounds}/{args.max_rounds}",
                        file=sys.stderr,
                    )

            time.sleep(args.interval)

            # Send heartbeat if enabled
            if args.heartbeat > 0:
                now = time.time()
                if now - last_heartbeat >= args.heartbeat:
                    send_heartbeat()
                    last_heartbeat = now

    except KeyboardInterrupt:
        print(
            f"\n[daemon] Stopped by user. Total messages processed: {total_messages}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[daemon] Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(
        f"[daemon] Stopped. Total messages: {total_messages}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
