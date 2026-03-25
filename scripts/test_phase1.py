#!/usr/bin/env python3
"""Phase 1 — 驗證 Supabase rooms + messages tables."""

import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# Test 1: Read all rooms
rooms = supabase.table("rooms").select("*").execute()
print("Rooms 總數:", len(rooms.data))
for room in rooms.data:
    print(f"  房間: {room['name']} (ID: {room['id']})")

# Test 2: Insert a message
if rooms.data:
    new_msg = {
        "room_id": rooms.data[0]["id"],
        "source": {"type": "agent", "id": "test_agent"},
        "action": "send",
        "content": "Phase 1 測試訊息！",
        "room": "lobby",
    }
    response = supabase.table("messages").insert(new_msg).execute()
    print("插入訊息成功！新訊息 ID:", response.data[0]["id"])

# Test 3: Query messages by room
msgs = supabase.table("messages").select("*").eq("room", "lobby").execute()
print("lobby 房間訊息數:", len(msgs.data))
