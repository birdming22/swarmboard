#!/usr/bin/env python3
"""Phase 2 verification — test send, persist, and broadcast."""

import json
import os
import sys
import time
import urllib.request

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8080"


def api(method, path, data=None, token=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main():
    # 1. Register a test agent
    print("=== Registering test agent ===")
    reg = api(
        "POST",
        "/auth/register",
        {
            "instance_id": f"test-agent-{int(time.time())}",
            "model_name": "test-model",
            "role": "ai_agent",
        },
    )
    token = reg["token"]
    print(f"Token: {token[:30]}...")

    # 2. Send message to lobby
    print("\n=== Send to lobby ===")
    r = api(
        "POST", "/send", {"content": "Phase 2 測試：lobby 訊息", "room": "lobby"}, token
    )
    print(f"Response: {r}")

    # 3. Send message to demo1
    print("\n=== Send to demo1 ===")
    r = api(
        "POST", "/send", {"content": "Phase 2 測試：demo1 訊息", "room": "demo1"}, token
    )
    print(f"Response: {r}")

    # 4. Join demo1 room
    print("\n=== Join demo1 ===")
    r = api("POST", "/send", {"content": "/join demo1"}, token)
    print(f"Response: {r}")

    # 5. Check rooms
    print("\n=== List rooms ===")
    r = api("GET", "/rooms", token=token)
    print(f"Rooms: {r}")

    # 6. Verify Supabase persistence
    print("\n=== Verify Supabase ===")
    from supabase import create_client

    sb = create_client(
        os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    )
    msgs = (
        sb.table("messages")
        .select("*")
        .order("timestamp", desc=True)
        .limit(5)
        .execute()
    )
    print(f"Latest 5 messages in Supabase:")
    for m in msgs.data:
        print(f"  [{m['room']}] {m['action']}: {m['content'][:60]}")

    print("\nPhase 2 verification 完成！")


if __name__ == "__main__":
    main()
