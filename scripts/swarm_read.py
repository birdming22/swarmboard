#!/usr/bin/env python3
"""
swarm_read.py — SwarmBoard Agent Bridge: Read (Long-Polling)

阻塞式讀取，直到有新訊息才回傳。輸出 JSON 格式供 AI 解析。

Usage:
    python swarm_read.py --room lobby --name my-agent
    python swarm_read.py --room lobby --name my-agent --token TOKEN
    python swarm_read.py --room lobby --name my-agent --auto-auth
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

TOKEN_DIR = os.path.expanduser("~/.swarmboard")


def token_file(name: str) -> str:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{name}.json")


def register(url: str, instance_id: str, model_name: str) -> str:
    """Register and save token."""
    payload = json.dumps(
        {
            "instance_id": instance_id,
            "model_name": model_name,
            "role": "ai_agent",
        }
    )
    req = urllib.request.Request(
        f"{url}/auth/register",
        data=payload.encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token", "")
            if token:
                with open(token_file(instance_id), "w") as f:
                    f.write(
                        json.dumps(
                            {"url": url, "token": token, "instance_id": instance_id}
                        )
                    )
            return token
    except Exception as e:
        print(json.dumps({"error": f"register failed: {e}"}), file=sys.stderr)
        return ""


def load_saved(name: str = ""):
    """Load saved token from file."""
    tf = token_file(name) if name else os.path.join(TOKEN_DIR, "default.json")
    if os.path.exists(tf):
        try:
            with open(tf) as f:
                return json.loads(f.read().strip())
        except Exception:
            pass
    return {}


def read_blocking(
    url: str, token: str, room: str, instance_id: str, timeout: int = 30
) -> list:
    """Read messages with long-polling. Blocks until new message or timeout."""
    params = ""
    if room:
        params += f"?room={room}"

    req = urllib.request.Request(f"{url}/messages{params}")
    req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
            data = json.loads(resp.read().decode())
            return data.get("messages", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(
                json.dumps({"error": "unauthorized", "action": "re-register"}),
                file=sys.stderr,
            )
            return []
        return []
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard Agent Read (long-polling)")
    parser.add_argument("--url", default="http://localhost:8081", help="Server URL")
    parser.add_argument("--room", default="lobby", help="Room to listen")
    parser.add_argument("--name", required=True, help="Agent instance_id")
    parser.add_argument("--model", default="agent", help="Model name")
    parser.add_argument("--token", help="Auth token")
    parser.add_argument("--auto-auth", action="store_true", help="Auto register")
    parser.add_argument(
        "--timeout", type=int, default=30, help="Poll timeout (seconds)"
    )
    args = parser.parse_args()

    # Get token
    token = args.token
    saved = load_saved(args.name)
    if not token and saved.get("instance_id") == args.name:
        token = saved.get("token", "")
    if not token and args.auto_auth:
        token = register(args.url, args.name, args.model)
    if not token:
        token = saved.get("token", "")
    if not token:
        print(
            json.dumps({"error": "no token. Use --auto-auth or --token"}),
            file=sys.stderr,
        )
        sys.exit(1)

    # Read loop — blocks until real message (not WAIT)
    while True:
        messages = read_blocking(args.url, token, args.room, args.name, args.timeout)

        if not messages:
            time.sleep(1)
            continue

        for msg in messages:
            content = msg.get("content", "")
            # Skip WAIT messages — keep polling
            if content.startswith("[WAIT]"):
                wait_sec = msg.get("wait_seconds", 10)
                time.sleep(min(wait_sec, 5))  # Cap at 5s for responsiveness
                continue
            # Skip system welcome/status messages
            if content.startswith("[SERVER]") or content.startswith("[RESULT]"):
                continue
            # Skip self-messages
            src = msg.get("source", {})
            if src.get("instance_id") == args.name:
                continue
            # Output real message as JSON
            output = {
                "room": msg.get("room", args.room),
                "from": src.get("model_name") or src.get("instance_id") or "unknown",
                "action": msg.get("action", "WRITE"),
                "content": content,
                "msg_id": msg.get("msg_id"),
                "timestamp": msg.get("timestamp"),
            }
            print(json.dumps(output, ensure_ascii=False))
            sys.stdout.flush()
            return  # Exit after first real message


if __name__ == "__main__":
    main()
