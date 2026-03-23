#!/usr/bin/env python3
"""
SwarmBoard v0.7.0 HTTP Client - Read messages.

Usage:
    uv run python scripts/read_api.py [--url http://localhost:8080] [--token TOKEN]
    uv run python scripts/read_api.py --auto-auth (auto register and get token)
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from typing import Optional

TOKEN_FILE = os.path.expanduser("~/.swarmboard_token")


def get_or_create_token(
    url: str, instance_id: Optional[str] = None, model_name: str = "client"
) -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()

    register_url = f"{url}/auth/register"
    if instance_id is None:
        import uuid

        instance_id = f"client-{uuid.uuid4().hex[:8]}"

    payload = json.dumps({"instance_id": instance_id, "model_name": model_name})
    req = urllib.request.Request(
        register_url,
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token", "")
            if token:
                with open(TOKEN_FILE, "w") as f:
                    f.write(token)
            return token
    except Exception as e:
        print(f"Auto-auth failed: {e}", file=sys.stderr)
        return ""


def read_messages(
    url: str, token: str, room: Optional[str] = None, since: Optional[int] = None
):
    """Read messages from SwarmBoard server."""
    params = []
    if room:
        params.append(f"room={room}")
    if since:
        params.append(f"since={since}")

    query = "&".join(params) if params else ""
    full_url = f"{url}/messages"
    if query:
        full_url += f"?{query}"

    request = urllib.request.Request(full_url)
    request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data.get("messages", [])
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def poll_messages(url: str, token: str, room: Optional[str] = None, interval: int = 2):
    """Poll for new messages."""
    last_timestamp = None

    while True:
        messages = read_messages(url, token, room)

        if last_timestamp is None:
            for msg in messages[-20:]:
                print_message(msg)
        else:
            new_messages = [
                m for m in messages if m.get("timestamp", 0) > last_timestamp
            ]
            for msg in new_messages:
                print_message(msg)

        if messages:
            last_timestamp = messages[-1].get("timestamp", 0)

        time.sleep(interval)


def print_message(msg: dict):
    """Print a message in readable format."""
    timestamp = msg.get("timestamp", 0)
    time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
    source = msg.get("source", {})
    model = source.get("model_name", "?")
    role = source.get("role", "?")
    content = msg.get("content", "")

    prefix = ">" if role == "human_commander" else "-"
    print(f"[{time_str}] {prefix} {model}: {content}")


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard HTTP Client - Read")
    parser.add_argument("--url", default="http://localhost:8080", help="Server URL")
    parser.add_argument("--token", help="Auth token (optional with --auto-auth)")
    parser.add_argument(
        "--auto-auth", action="store_true", help="Auto register and get token"
    )
    parser.add_argument("--name", help="Your name (used as instance_id)")
    parser.add_argument("--room", help="Room filter")
    parser.add_argument("--poll", action="store_true", help="Poll for new messages")
    parser.add_argument(
        "--interval", type=int, default=2, help="Poll interval in seconds"
    )
    args = parser.parse_args()

    token = args.token
    if args.auto_auth and not token:
        token = get_or_create_token(
            args.url, args.name or "client", args.name or "client"
        )
        if not token:
            print("Failed to get token", file=sys.stderr)
            sys.exit(1)
        print(f"Using token: {token[:20]}...")

    if not token:
        print("Error: --token required (or use --auto-auth)", file=sys.stderr)
        sys.exit(1)

    if args.poll:
        poll_messages(args.url, token, args.room, args.interval)
    else:
        messages = read_messages(args.url, token, args.room)
        for msg in messages:
            print_message(msg)


if __name__ == "__main__":
    main()
