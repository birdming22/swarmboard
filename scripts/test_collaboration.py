#!/usr/bin/env python3
"""
Test script for multi-agent collaboration flow.
Tests daemon, @mention filtering, and confirmation mechanism.

Usage:
  python scripts/test_collaboration.py --model nemotron-3-super-free
"""

import argparse
import subprocess
import sys
import time


def run_command(cmd, description):
    print(f"\n{'=' * 60}")
    print(f"[test] {description}")
    print(f"[test] Command: {cmd}")
    print("=" * 60)

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode == 0:
        print(f"[test] ✓ Success")
        if result.stdout:
            print(f"[test] Output: {result.stdout[:200]}")
    else:
        print(f"[test] ✗ Failed")
        if result.stderr:
            print(f"[test] Error: {result.stderr[:200]}")

    return result.returncode == 0


def test_send_message(model):
    return run_command(
        f'cd /home/k200/workspace/swarmboard && uv run python scripts/send.py "測試訊息：多 Agent 協作測試" --model {model}',
        "Test sending message to blackboard",
    )


def test_read_blackboard():
    return run_command(
        "cd /home/k200/workspace/swarmboard && uv run python scripts/read.py",
        "Test reading blackboard",
    )


def test_check_new_messages(model):
    return run_command(
        f"cd /home/k200/workspace/swarmboard && uv run python scripts/check.py --last-id msg-000 --exclude-self {model}",
        "Test checking new messages",
    )


def test_send_confirmation(model):
    return run_command(
        f'cd /home/k200/workspace/swarmboard && uv run python scripts/confirm.py --model {model} --status received --task "測試確認機制"',
        "Test sending confirmation",
    )


def test_status_report(model):
    return run_command(
        f"cd /home/k200/workspace/swarmboard && uv run python scripts/status.py --status listening --model {model}",
        "Test status reporting",
    )


def main():
    parser = argparse.ArgumentParser(description="Test multi-agent collaboration")
    parser.add_argument("--model", required=True, help="Model name to test with")
    args = parser.parse_args()

    print(f"[test] Starting multi-agent collaboration test for {args.model}")

    tests = [
        ("Send message", lambda: test_send_message(args.model)),
        ("Read blackboard", test_read_blackboard),
        ("Check new messages", lambda: test_check_new_messages(args.model)),
        ("Send confirmation", lambda: test_send_confirmation(args.model)),
        ("Status report", lambda: test_status_report(args.model)),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[test] ✗ {name} failed with exception: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"[test] Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
