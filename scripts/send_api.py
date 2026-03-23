#!/usr/bin/env python3
"""
SwarmBoard v0.7.0 HTTP Client - Send messages.

Usage:
    uv run python scripts/send_api.py "message content" [--url http://localhost:8080] [--token TOKEN]
    uv run python scripts/send_api.py "message" --auto-auth (auto register and get token)
"""

import argparse
import json
import os
import sys
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


def send_message(url: str, token: str, content: str, room: Optional[str] = None):
    """Send a message to SwarmBoard server."""
    full_url = f"{url}/send"

    payload = {"content": content}
    if room:
        payload["room"] = room

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        full_url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode())
            print(f"Message sent: {result.get('msg_id', 'unknown')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP Error: {e.code} {e.reason}", file=sys.stderr)
        print(f"Response: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Connection Error: {e.reason}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard HTTP Client - Send")
    parser.add_argument("message", help="Message content")
    parser.add_argument("--url", default="http://localhost:8080", help="Server URL")
    parser.add_argument("--token", help="Auth token (optional with --auto-auth)")
    parser.add_argument(
        "--auto-auth", action="store_true", help="Auto register and get token"
    )
    parser.add_argument("--name", help="Your name (used as instance_id)")
    parser.add_argument("--room", help="Room name")
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

    send_message(args.url, token, args.message, args.room)


if __name__ == "__main__":
    main()
