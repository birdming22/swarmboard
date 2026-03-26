#!/usr/bin/env python3
"""
swarm_send.py — SwarmBoard Agent Bridge: Send

發送訊息到指定房間。輸出 JSON 格式確認結果。

Usage:
    python swarm_send.py --room lobby --content "Hello!" --name my-agent
    python swarm_send.py --room lobby --content "Hello!" --name my-agent --auto-auth
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error

TOKEN_DIR = os.path.expanduser("~/.swarmboard")


def token_file(name: str) -> str:
    os.makedirs(TOKEN_DIR, exist_ok=True)
    return os.path.join(TOKEN_DIR, f"{name}.json")


def register(url: str, instance_id: str, model_name: str) -> str:
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


def load_saved(name: str) -> dict:
    tf = token_file(name)
    if os.path.exists(tf):
        try:
            with open(tf) as f:
                return json.loads(f.read().strip())
        except Exception:
            pass
    return {}


def send(url: str, token: str, content: str, room: str) -> dict:
    payload = json.dumps({"content": content, "room": room})
    req = urllib.request.Request(
        f"{url}/send",
        data=payload.encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard Agent Send")
    parser.add_argument("--url", default="http://localhost:8081", help="Server URL")
    parser.add_argument("--room", default="lobby", help="Room to send to")
    parser.add_argument("--content", required=True, help="Message content")
    parser.add_argument("--name", required=True, help="Agent instance_id")
    parser.add_argument("--model", default="agent", help="Model name")
    parser.add_argument("--token", help="Auth token")
    parser.add_argument("--auto-auth", action="store_true", help="Auto register")
    args = parser.parse_args()

    # Get token
    token = args.token
    saved = load_saved(args.name)
    if not token and saved.get("instance_id") == args.name:
        token = saved.get("token", "")
    if not token and args.auto_auth:
        token = register(args.url, args.name, args.model)
    if not token:
        print(
            json.dumps({"error": "no token. Use --auto-auth or --token"}),
            file=sys.stderr,
        )
        sys.exit(1)

    result = send(args.url, token, args.content, args.room)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
