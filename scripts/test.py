#!/usr/bin/env python3
"""
Automated test runner for SwarmBoard.
Runs all tests and reports results.

Usage:
  python scripts/test.py [--verbose]
"""

import argparse
import json
import subprocess
import sys
import time


def run_test(name, command, timeout=30):
    """Run a single test and return result."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True,
        )
        return {
            "name": name,
            "passed": result.returncode == 0,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "passed": False,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "returncode": -1,
        }
    except Exception as e:
        return {
            "name": name,
            "passed": False,
            "stdout": "",
            "stderr": str(e),
            "returncode": -1,
        }


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard test runner")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    tests = [
        {
            "name": "init.py help",
            "command": "uv run python scripts/init.py --help",
        },
        {
            "name": "send.py help",
            "command": "uv run python scripts/send.py --help",
        },
        {
            "name": "read.py help",
            "command": "uv run python scripts/read.py --help",
        },
        {
            "name": "check.py help",
            "command": "uv run python scripts/check.py --help",
        },
        {
            "name": "status.py help",
            "command": "uv run python scripts/status.py --help",
        },
        {
            "name": "daemon.py help",
            "command": "uv run python scripts/daemon.py --help",
        },
        {
            "name": "read blackboard",
            "command": "uv run python scripts/read.py",
        },
    ]

    print(f"Running {len(tests)} tests...\n")

    results = []
    passed = 0
    failed = 0

    for test in tests:
        result = run_test(test["name"], test["command"])
        results.append(result)

        if result["passed"]:
            passed += 1
            status = "✅ PASS"
        else:
            failed += 1
            status = "❌ FAIL"

        print(f"{status}: {result['name']}")

        if args.verbose or not result["passed"]:
            if result["stdout"]:
                print(f"  stdout: {result['stdout'][:200]}")
            if result["stderr"]:
                print(f"  stderr: {result['stderr'][:200]}")

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'=' * 50}")

    # Save results to file
    with open("test_results.json", "w") as f:
        json.dump(
            {
                "timestamp": time.time(),
                "passed": passed,
                "failed": failed,
                "total": len(tests),
                "results": results,
            },
            f,
            indent=2,
        )

    print(f"\nResults saved to test_results.json")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
