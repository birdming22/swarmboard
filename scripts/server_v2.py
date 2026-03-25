#!/usr/bin/env python3
"""
SwarmBoard v0.7.0 - Pure FastAPI Server with Token Auth and Room Support.

Features:
- Pure HTTP/WebSocket (no ZMQ dependency)
- Token-based authentication (JWT)
- Multi-room support
- Live reload for development

Usage:
    uv run python scripts/server_v2.py [--port 8080] [--reload]
"""

import argparse
import json
import os
import random
import sys
import time
import uuid
import hashlib
import base64
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    Header,
)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from loguru import logger
import trio
from hypercorn.config import Config
from hypercorn.trio import serve

from dotenv import load_dotenv
from supabase import create_client, Client
from upstash_redis import Redis

load_dotenv()

# Supabase client (service_role key for server-side)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
supabase: Client | None = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Upstash Redis client
redis: Redis | None = None
try:
    redis = Redis.from_env()
except Exception:
    pass  # Upstash not configured yet

# Upstash QStash client
qstash = None
QSTASH_TOKEN = os.getenv("QSTASH_TOKEN", "")
QSTASH_CURRENT_SIGNING_KEY = os.getenv("QSTASH_CURRENT_SIGNING_KEY", "")
QSTASH_NEXT_SIGNING_KEY = os.getenv("QSTASH_NEXT_SIGNING_KEY", "")
if QSTASH_TOKEN:
    try:
        from qstash import QStash

        qstash = QStash(token=QSTASH_TOKEN)
    except Exception:
        pass  # qstash not installed

# Room UUID cache: room_name -> room_id (from Supabase)
_room_id_cache: dict[str, str] = {}


def get_room_id(room_name: str) -> str | None:
    """Resolve room name to Supabase UUID. Returns None if room doesn't exist."""
    if room_name in _room_id_cache:
        return _room_id_cache[room_name]
    if not supabase:
        return None
    try:
        result = supabase.table("rooms").select("id").eq("name", room_name).execute()
        if result.data:
            room_id = result.data[0]["id"]
            _room_id_cache[room_name] = room_id
            return room_id
    except Exception as e:
        logger.error(f"Failed to resolve room '{room_name}': {e}")
    return None


def persist_message_to_supabase(msg: dict, room_name: str) -> str | None:
    """Persist a message to Supabase messages table. Returns message ID or None."""
    if not supabase:
        return None
    room_id = get_room_id(room_name)
    if not room_id:
        logger.warning(f"Cannot persist: room '{room_name}' not found in Supabase")
        return None
    try:
        row = {
            "room_id": room_id,
            "msg_id": msg.get("msg_id"),
            "source": msg.get("source", {}),
            "action": msg.get("action", "WRITE"),
            "content": msg.get("content", ""),
            "room": room_name,
        }
        result = supabase.table("messages").insert(row).execute()
        if result.data:
            return result.data[0].get("id")
    except Exception as e:
        logger.error(f"Failed to persist message to Supabase: {e}")
    return None


async def broadcast_to_room(room_name: str, payload: dict):
    """Broadcast a message to a Supabase Realtime channel for the given room.
    This enables cross-platform clients (Python agents, Web UI) to receive messages in real-time.
    """
    if not supabase:
        return
    try:
        channel_name = f"realtime:room:{room_name}"
        channel = supabase.channel(channel_name)
        # supabase-py channel API: send_broadcast(event, payload)
        channel.send_broadcast(
            "message", {"type": "broadcast", "event": "message", "payload": payload}
        )  # type: ignore[attr-defined]
        logger.debug(f"Broadcast to {room_name}: {payload.get('content', '')[:50]}")
    except Exception as e:
        logger.warning(f"Realtime broadcast failed for {room_name}: {e}")


# ================== Redis Helpers ==================


def redis_add_online(room: str, agent_id: str) -> bool:
    """Add agent to online set for a room (Redis Sorted Set)."""
    if not redis:
        return False
    try:
        key = f"online:{room}"
        now = int(time.time())
        redis.zadd(key, {agent_id: now})
        # Cleanup agents offline > 5 min
        redis.zremrangebyscore(key, 0, now - 300)
        logger.debug(f"Redis: {agent_id} online in {room}")
        return True
    except Exception as e:
        logger.warning(f"Redis add_online failed: {e}")
        return False


def redis_remove_online(room: str, agent_id: str) -> bool:
    """Remove agent from online set for a room."""
    if not redis:
        return False
    try:
        redis.zrem(f"online:{room}", agent_id)
        return True
    except Exception as e:
        logger.warning(f"Redis remove_online failed: {e}")
        return False


def redis_get_online(room: str) -> list[str]:
    """Get list of online agents in a room."""
    if not redis:
        return []
    try:
        now = int(time.time())
        key = f"online:{room}"
        # Cleanup expired first
        redis.zremrangebyscore(key, 0, now - 300)
        members = redis.zrange(key, 0, -1)
        return [m if isinstance(m, str) else m.decode() for m in members]
    except Exception as e:
        logger.warning(f"Redis get_online failed: {e}")
        return []


def redis_rate_limit(agent_id: str, limit: int = 30, window: int = 60) -> bool:
    """Check rate limit. Returns True if allowed, False if exceeded."""
    if not redis:
        return True  # No Redis = no limit
    try:
        key = f"rate:{agent_id}"
        current = redis.incr(key)
        if current == 1:
            redis.expire(key, window)
        return current <= limit
    except Exception as e:
        logger.warning(f"Redis rate_limit failed: {e}")
        return True


def redis_set_task(task_id: str, data: dict, ttl: int = 3600) -> bool:
    """Store task status in Redis Hash."""
    if not redis:
        return False
    try:
        key = f"task:{task_id}"
        for k, v in data.items():
            redis.hset(key, k, str(v))
        redis.expire(key, ttl)
        return True
    except Exception as e:
        logger.warning(f"Redis set_task failed: {e}")
        return False


def redis_get_task(task_id: str) -> dict | None:
    """Get task status from Redis Hash."""
    if not redis:
        return None
    try:
        key = f"task:{task_id}"
        data = redis.hgetall(key)
        return data if data else None
    except Exception as e:
        logger.warning(f"Redis get_task failed: {e}")
        return None


SERVER_VERSION = "0.7.0"

LOG_FILE = Path(__file__).parent.parent / "logs" / "server_v2.log"
LOG_FILE.parent.mkdir(exist_ok=True)
logger.add(
    LOG_FILE,
    rotation="10 MB",
    retention="1 day",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
)

DATA_FILE = Path(__file__).parent.parent / "data" / "server_v2.json"
DATA_FILE.parent.mkdir(exist_ok=True)


def create_token(instance_id: str, secret: str = "swarmboard-secret") -> str:
    """Create a simple JWT-like token."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": instance_id,
                    "iat": int(time.time()),
                    "exp": int(time.time()) + 86400 * 7,  # 7 days
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )

    signature = (
        base64.urlsafe_b64encode(
            hmac.new(
                secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
            ).digest()
        )
        .decode()
        .rstrip("=")
    )

    return f"{header}.{payload}.{signature}"


def verify_token(token: str, secret: str = "swarmboard-secret") -> Optional[str]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header, payload, signature = parts

        # Verify signature
        expected_sig = (
            base64.urlsafe_b64encode(
                hmac.new(
                    secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256
                ).digest()
            )
            .decode()
            .rstrip("=")
        )

        if signature != expected_sig:
            return None

        # Decode payload - ensure we handle bytes properly
        payload_bytes = payload.encode() + b"=="
        decoded = base64.urlsafe_b64decode(payload_bytes)
        payload_data = json.loads(decoded)

        if payload_data.get("exp", 0) < time.time():
            return None

        return payload_data.get("sub")
    except Exception as e:
        print(f"Token verify error: {e}")
        return None


# ================== Data Models ==================


class Message(BaseModel):
    content: str
    session: Optional[str] = None
    room: Optional[str] = None


class AuthRequest(BaseModel):
    instance_id: str
    model_name: str = "unknown"
    role: str = "ai_agent"
    name: str = ""  # Display name for introductions


class RoomCreate(BaseModel):
    name: str


# ================== App State ==================

app = FastAPI(title="SwarmBoard v0.7.0")

# In-memory storage
messages: list[dict] = []
rooms: dict[str, dict] = {"lobby": {"name": "lobby", "messages": [], "members": set()}}
current_session_id = f"session-{int(time.time())}"
sessions: dict[str, dict] = {}

# Connected WebSocket clients
ws_clients: list[WebSocket] = []

# Token storage
tokens: dict[str, dict] = {}

# Track registered names (for duplicate check)
registered_names: dict[str, str] = {}

# Track online agents: {instance_id: last_heartbeat}
online_agents: dict[str, int] = {}

# Track clients that have called /messages (for welcome message)
seen_clients: set[str] = set()

# Track last read timestamp per client: {instance_id: last_timestamp}
last_read: dict[str, int] = {}

# Pre-register Commander token for Web UI (port set in main())
COMMANDER_TOKEN = create_token(
    "commander-web", secret="swarmboard-secret"
)  # JWT format
commander_url = ""  # will be set in main()


def get_commander_url(port: int) -> str:
    return f"http://localhost:{port}/#token={COMMANDER_TOKEN}"


tokens[COMMANDER_TOKEN] = {
    "instance_id": "web-commander",
    "model_name": "commander",
    "role": "human_commander",
}


def save_state():
    try:
        state = {
            "messages": messages,
            "rooms": {
                k: {
                    "name": v["name"],
                    "messages": v["messages"],
                    "members": list(v["members"]),
                }
                for k, v in rooms.items()
            },
            "current_session_id": current_session_id,
            "sessions": sessions,
            "registered_names": registered_names,
        }
        DATA_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        logger.debug(f"Saved {len(messages)} messages to {DATA_FILE}")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def load_state():
    global messages, rooms, current_session_id, sessions, registered_names
    if DATA_FILE.exists():
        try:
            state = json.loads(DATA_FILE.read_text())
            messages = state.get("messages", [])
            rooms = {
                k: {
                    "name": v["name"],
                    "messages": v["messages"],
                    "members": set(v["members"]),
                }
                for k, v in state.get(
                    "rooms", {"lobby": {"name": "lobby", "messages": [], "members": []}}
                ).items()
            }
            current_session_id = state.get("current_session_id", current_session_id)
            sessions = state.get("sessions", {})
            registered_names = state.get("registered_names", {})
            logger.info(
                f"Loaded {len(messages)} messages, {len(rooms)} rooms from {DATA_FILE}"
            )
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")


# Load state on startup
load_state()


# ================== Auth Endpoints ==================


@app.post("/auth/register")
async def register(auth: AuthRequest):
    """Register and get token."""
    instance_id = auth.instance_id

    # Check for duplicate name
    if instance_id in registered_names:
        existing_token = registered_names[instance_id]
        raise HTTPException(
            status_code=409,
            detail=f"名字 '{instance_id}' 已被使用。請換一個名字（例如: {instance_id}-2）",
        )

    token = create_token(instance_id)
    tokens[token] = {
        "instance_id": instance_id,
        "model_name": auth.model_name,
        "role": auth.role,
        "created_at": time.time(),
    }
    registered_names[instance_id] = token
    save_state()
    logger.info(f"Registered: {instance_id} ({auth.model_name})")
    return {"token": token, "instance_id": instance_id}


async def get_current_client(authorization: Optional[str] = Header(None)) -> dict:
    """Get current authenticated client."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = authorization.replace("Bearer ", "")

    # Check if token is the commander token
    if token == COMMANDER_TOKEN:
        return {
            "instance_id": "web-commander",
            "model_name": "commander",
            "role": "human_commander",
        }

    # Check if token is in registered tokens
    if token in tokens:
        return tokens[token]

    # Invalid token
    raise HTTPException(status_code=401, detail="Invalid token")


# ================== Message Endpoints ==================


@app.get("/messages")
async def get_messages(
    session: Optional[str] = None,
    room: Optional[str] = None,
    since: Optional[int] = None,
    mentions: Optional[str] = None,
    client: dict = Depends(get_current_client),
):
    """Get messages filtered by session/room/since/mentions."""
    filtered = messages.copy()
    instance_id = client.get("instance_id", "unknown")

    # Filter by session
    if session:
        filtered = [m for m in filtered if m.get("session") == session]
    elif current_session_id:
        filtered = [m for m in filtered if m.get("session") == current_session_id]

    # Filter by room
    if room:
        room_obj = rooms.get(room)
        if room_obj:
            filtered = [m for m in filtered if m.get("room") == room]
        else:
            filtered = []

    last_ts = last_read.get(instance_id, 0)
    if since is None:
        since = last_ts
    filtered = [m for m in filtered if m.get("timestamp", 0) > since]

    if filtered:
        last_read[instance_id] = filtered[-1].get("timestamp", 0)

    if mentions and mentions.lower() == "true":
        mention_tasks = [
            m
            for m in filtered
            if (
                f"@{instance_id}" in m.get("content", "")
                or "@all" in m.get("content", "")
            )
            and m.get("assigned_to") != instance_id
            and not m.get("content", "").startswith("[RESULT]")
            and m.get("source", {}).get("instance_id") != instance_id
        ]

        if mention_tasks:
            mention_tasks[0]["assigned_to"] = instance_id
            save_state()
            logger.info(
                f"Assigned task to {instance_id}: {mention_tasks[0].get('content', '')[:50]}"
            )
            filtered = mention_tasks[:1]
        else:
            wait_seconds = random.randint(10, 120)
            wait_msg = {
                "msg_id": f"wait-{int(time.time())}",
                "timestamp": int(time.time()),
                "source": {
                    "instance_id": "server",
                    "model_name": "system",
                    "role": "system",
                },
                "content": f"[WAIT] 沒有新任務，請 {wait_seconds} 秒後再來領取",
                "wait_seconds": wait_seconds,
                "session": current_session_id,
            }
            filtered = [wait_msg]
            logger.info(f"WAIT for {instance_id}: {wait_seconds}s")

    # Check if new client - inject welcome as system message (only for this client)
    if instance_id not in seen_clients:
        seen_clients.add(instance_id)
        welcome_msg = {
            "msg_id": f"sys-{int(time.time())}",
            "timestamp": int(time.time()),
            "source": {
                "instance_id": "server",
                "model_name": "system",
                "role": "system",
            },
            "content": "[SERVER] 歡迎！請告訴我你的名字（用 /name <你的名字>）",
            "session": current_session_id,
        }
        filtered = [welcome_msg] + filtered

    # Return last 100 messages
    return {"messages": filtered[-100:], "session": current_session_id}


@app.get("/messages/latest")
async def get_latest(client: dict = Depends(get_current_client)):
    """Get latest message timestamp."""
    if messages:
        latest = messages[-1].get("timestamp", 0)
    else:
        latest = 0
    return {"latest_timestamp": latest, "session": current_session_id}


@app.post("/send")
async def send_message(message: Message, client: dict = Depends(get_current_client)):
    """Send a message."""
    agent_id = client["instance_id"]

    # Rate limit check (Redis-backed)
    if not redis_rate_limit(agent_id):
        return {"status": "error", "response": "Rate limit exceeded (30 msg/min)"}

    # Handle commands
    if message.content.startswith("/"):
        response = await handle_command(message.content, client)
        # Save command response to messages if it's not an error
        if response.get("status") == "ok":
            resp_content = response.get("response", "")
            if resp_content:
                cmd_msg = {
                    "msg_id": f"cmd-{uuid.uuid4().hex[:8]}",
                    "timestamp": int(time.time()),
                    "source": {
                        "instance_id": "server",
                        "model_name": "system",
                        "role": "system",
                    },
                    "action": "COMMAND",
                    "content": resp_content,
                    "session": current_session_id,
                    "room": message.room or "lobby",
                }
                messages.append(cmd_msg)
                # Persist command response to Supabase
                persist_message_to_supabase(cmd_msg, message.room or "lobby")
                save_state()
        return response

    # Create message
    room_name = message.room or "lobby"
    msg = {
        "msg_id": f"msg-{uuid.uuid4().hex[:8]}",
        "timestamp": int(time.time()),
        "source": {
            "instance_id": client["instance_id"],
            "model_name": client.get("model_name", "unknown"),
            "role": client.get("role", "ai_agent"),
        },
        "action": "WRITE",
        "content": message.content,
        "session": message.session or current_session_id,
        "room": room_name,
    }

    # 1. Persist to in-memory
    messages.append(msg)
    if room_name in rooms:
        rooms[room_name]["messages"].append(msg)

    # 2. Persist to Supabase (async, non-blocking)
    persist_message_to_supabase(msg, room_name)

    # 3. Broadcast via Supabase Realtime channel
    await broadcast_to_room(room_name, msg)

    # 4. Broadcast to local WebSocket clients
    await broadcast_message(msg)

    save_state()

    logger.info(
        f"WRITE from {client['instance_id']} to #{room_name}: {message.content[:80]}"
    )
    return {"status": "ok", "msg_id": msg["msg_id"], "room": room_name}


async def handle_command(content: str, client: dict) -> dict:
    """Handle slash commands."""
    global current_session_id, messages, rooms, sessions, tokens
    cmd = content.split()[0].lower()

    if cmd == "/help":
        return {
            "status": "ok",
            "response": "Commands: /help, /status, /new-session, /rooms, /online, /create <name>, /join <name>, /leave",
        }

    elif cmd == "/online":
        # Try Redis first, fallback to in-memory
        all_online = set()
        for room_name in rooms:
            all_online.update(redis_get_online(room_name))
        if not all_online:
            # Fallback to in-memory
            now = int(time.time())
            all_online = {uid for uid, t in online_agents.items() if now - t < 60}
        if all_online:
            return {
                "status": "ok",
                "response": f"在線用戶 ({len(all_online)}): {', '.join(sorted(all_online))}",
            }
        return {"status": "ok", "response": "目前沒有在線用戶"}

    elif cmd == "/status":
        return {
            "status": "ok",
            "response": f"SwarmBoard v0.7.0 | Session: {current_session_id} | Messages: {len(messages)} | Rooms: {len(rooms)} | Clients: {len(tokens)}",
        }

    elif cmd == "/new-session":
        current_session_id = f"session-{int(time.time())}"
        sessions[current_session_id] = {"created_at": time.time(), "messages": []}
        return {
            "status": "ok",
            "response": f"New session created: {current_session_id}",
        }

    elif cmd == "/rooms":
        room_list = [
            {"name": name, "members": len(data["members"])}
            for name, data in rooms.items()
        ]
        return {"status": "ok", "rooms": room_list}

    elif cmd == "/create":
        parts = content.split()
        if len(parts) < 2:
            return {"status": "error", "response": "Usage: /create <room_name>"}
        room_name = parts[1].lower()
        if room_name in rooms:
            return {"status": "error", "response": f"Room '{room_name}' already exists"}
        rooms[room_name] = {"name": room_name, "messages": [], "members": set()}
        return {"status": "ok", "response": f"Room '{room_name}' created"}

    elif cmd == "/join":
        parts = content.split()
        if len(parts) < 2:
            return {"status": "error", "response": "Usage: /join <room_name>"}
        room_name = parts[1].lower()
        if room_name not in rooms:
            return {"status": "error", "response": f"Room '{room_name}' not found"}
        rooms[room_name]["members"].add(client["instance_id"])
        save_state()
        agent_id = client["instance_id"]
        logger.info(f"{agent_id} joined {room_name}")

        # Track online in Redis
        redis_add_online(room_name, agent_id)

        # Broadcast join event
        join_msg = {
            "msg_id": f"join-{uuid.uuid4().hex[:8]}",
            "timestamp": int(time.time()),
            "source": {
                "instance_id": agent_id,
                "model_name": client.get("model_name", "unknown"),
                "role": client.get("role", "ai_agent"),
            },
            "action": "ROOM_JOIN",
            "content": f"[JOIN] {agent_id} 已加入房間 {room_name}",
            "room": room_name,
        }
        persist_message_to_supabase(join_msg, room_name)
        await broadcast_to_room(room_name, join_msg)
        await broadcast_message(join_msg)

        return {
            "status": "ok",
            "response": f"已加入房間 '{room_name}'（目前 {len(rooms[room_name]['members'])} 人）",
        }

    elif cmd == "/leave":
        room_name = content.split()[1].lower() if len(content.split()) > 1 else None
        left_rooms = []
        if room_name:
            if (
                room_name in rooms
                and client["instance_id"] in rooms[room_name]["members"]
            ):
                rooms[room_name]["members"].discard(client["instance_id"])
                left_rooms.append(room_name)
        else:
            for name, data in rooms.items():
                if client["instance_id"] in data["members"]:
                    data["members"].discard(client["instance_id"])
                    left_rooms.append(name)
        save_state()
        if left_rooms:
            agent_id = client["instance_id"]
            logger.info(f"{agent_id} left {', '.join(left_rooms)}")

            # Broadcast leave event to each room
            for r in left_rooms:
                redis_remove_online(r, agent_id)
                leave_msg = {
                    "msg_id": f"leave-{uuid.uuid4().hex[:8]}",
                    "timestamp": int(time.time()),
                    "source": {
                        "instance_id": agent_id,
                        "model_name": client.get("model_name", "unknown"),
                        "role": client.get("role", "ai_agent"),
                    },
                    "action": "ROOM_LEAVE",
                    "content": f"[LEAVE] {agent_id} 已離開房間 {r}",
                    "room": r,
                }
                persist_message_to_supabase(leave_msg, r)
                await broadcast_to_room(r, leave_msg)
                await broadcast_message(leave_msg)

            return {"status": "ok", "response": f"已離開房間：{', '.join(left_rooms)}"}
        return {"status": "ok", "response": "你沒有在任何房間"}

    else:
        return {"status": "error", "response": f"Unknown command: {cmd}"}


# ================== Room Endpoints ==================


@app.get("/rooms")
async def list_rooms(client: dict = Depends(get_current_client)):
    """List all rooms."""
    room_list = [
        {"name": name, "message_count": len(data["messages"])}
        for name, data in rooms.items()
    ]
    return {"rooms": room_list}


@app.post("/rooms")
async def create_room(room: RoomCreate, client: dict = Depends(get_current_client)):
    """Create a new room."""
    name = room.name.lower()
    if name in rooms:
        raise HTTPException(status_code=400, detail="Room already exists")
    rooms[name] = {"name": name, "messages": [], "members": set()}
    return {"status": "ok", "room": name}


@app.post("/rooms/{room_name}/join")
async def join_room(room_name: str, client: dict = Depends(get_current_client)):
    """Join a room."""
    if room_name not in rooms:
        raise HTTPException(status_code=404, detail="Room not found")
    rooms[room_name]["members"].add(client["instance_id"])
    return {"status": "ok", "room": room_name}


@app.post("/rooms/{room_name}/leave")
async def leave_room(room_name: str, client: dict = Depends(get_current_client)):
    """Leave a room."""
    if room_name in rooms:
        rooms[room_name]["members"].discard(client["instance_id"])
    return {"status": "ok"}


# ================== Session Endpoints ==================


@app.post("/session/new")
async def new_session(client: dict = Depends(get_current_client)):
    global current_session_id, messages, rooms, sessions, tokens
    current_session_id = f"session-{int(time.time())}"
    sessions[current_session_id] = {"created_at": time.time()}
    return {"session": current_session_id}


@app.get("/session")
async def get_session(client: dict = Depends(get_current_client)):
    """Get current session info."""
    return {
        "session_id": current_session_id,
        "message_count": len(
            [m for m in messages if m.get("session") == current_session_id]
        ),
    }


# ================== Status Endpoint ==================


@app.get("/status")
async def get_status(client: dict = Depends(get_current_client)):
    """Get server status."""
    now = int(time.time())
    online_count = sum(1 for t in online_agents.values() if now - t < 60)
    return {
        "version": "0.7.0",
        "session": current_session_id,
        "messages": len(messages),
        "rooms": len(rooms),
        "connected_clients": len(tokens),
        "online_agents": online_count,
        "ws_clients": len(ws_clients),
    }


@app.post("/heartbeat")
async def heartbeat(client: dict = Depends(get_current_client)):
    """Update heartbeat timestamp and cleanup expired agents."""
    instance_id = client["instance_id"]
    now = int(time.time())
    online_agents[instance_id] = now

    # Cleanup expired agents (no heartbeat for 90 seconds)
    expired = [uid for uid, t in list(online_agents.items()) if now - t > 90]
    for uid in expired:
        del online_agents[uid]
        if uid in registered_names:
            del registered_names[uid]
            logger.info(f"Kicked expired agent: {uid}")

    return {"status": "ok", "instance_id": instance_id}


# ================== QStash Task Queue ==================


class TaskRequest(BaseModel):
    room: str = "lobby"
    task_type: str = "process_message"
    payload: dict = {}


@app.post("/queue/task")
async def queue_task(task: TaskRequest, client: dict = Depends(get_current_client)):
    """Queue an async task via QStash."""
    if not qstash:
        return {"status": "error", "response": "QStash not configured"}

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    callback_url = os.getenv(
        "QSTASH_CALLBACK_URL", "http://localhost:8081/qstash/callback"
    )

    # Store task in Redis
    redis_set_task(
        task_id,
        {
            "status": "queued",
            "room": task.room,
            "task_type": task.task_type,
            "requested_by": client["instance_id"],
            "created_at": int(time.time()),
        },
    )

    try:
        result = qstash.message.publish_json(
            url=callback_url,
            body={
                "task_id": task_id,
                "room": task.room,
                "task_type": task.task_type,
                "payload": task.payload,
                "requested_by": client["instance_id"],
            },
            retries=3,
        )
        logger.info(f"Queued task {task_id} via QStash: {result}")
        return {"status": "queued", "task_id": task_id}
    except Exception as e:
        logger.error(f"QStash publish failed: {e}")
        return {"status": "error", "response": str(e)}


@app.post("/qstash/callback")
async def qstash_callback(request: dict):
    """Receive task results from QStash worker."""
    task_id = request.get("task_id", "unknown")
    room = request.get("room", "lobby")
    task_type = request.get("task_type", "unknown")
    result = request.get("result", "Task completed")

    logger.info(f"QStash callback: task_id={task_id} room={room} type={task_type}")

    # Update task status in Redis
    redis_set_task(
        task_id,
        {
            "status": "completed",
            "room": room,
            "task_type": task_type,
            "completed_at": int(time.time()),
        },
    )

    # Broadcast result to room
    result_msg = {
        "msg_id": f"task-{uuid.uuid4().hex[:8]}",
        "timestamp": int(time.time()),
        "source": {
            "instance_id": "qstash-worker",
            "model_name": "system",
            "role": "system",
        },
        "action": "TASK_COMPLETE",
        "content": f"[RESULT] 任務 {task_type} 完成: {result}",
        "room": room,
    }
    persist_message_to_supabase(result_msg, room)
    await broadcast_to_room(room, result_msg)
    await broadcast_message(result_msg)

    return {"status": "processed", "task_id": task_id}


@app.get("/queue/status/{task_id}")
async def get_task_status(task_id: str, client: dict = Depends(get_current_client)):
    """Get task status from Redis."""
    task = redis_get_task(task_id)
    if task:
        return {"task_id": task_id, **task}
    return {"task_id": task_id, "status": "not_found"}


# ================== WebSocket Endpoint ==================


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, instance_id: Optional[str] = None):
    """WebSocket for real-time updates."""
    await websocket.accept()
    ws_clients.append(websocket)

    # Send welcome message to new client
    if instance_id:
        await websocket.send_json(
            {
                "type": "welcome",
                "data": {
                    "message": "歡迎來到 SwarmBoard！請告訴我你的名字（用 /name <名字>）",
                    "instance_id": instance_id,
                },
            }
        )

    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
    except Exception:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


async def broadcast_message(msg: dict):
    """Broadcast message to all WebSocket clients."""
    disconnected = []
    for client in ws_clients:
        try:
            await client.send_json({"type": "new_message", "data": msg})
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        if client in ws_clients:
            ws_clients.remove(client)


async def welcome_client(websocket: WebSocket, instance_id: str):
    """Send welcome message to newly registered client."""
    try:
        await websocket.send_json(
            {
                "type": "welcome",
                "data": {
                    "message": "歡迎來到 SwarmBoard！請問你的名字是？請回覆你的名稱（例如：/name kilo）",
                    "instance_id": instance_id,
                },
            }
        )
    except Exception:
        pass


# ================== Web UI ==================


@app.get("/", response_class=HTMLResponse)
async def home():
    """Web UI."""
    recent_messages = messages[-50:]

    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>SwarmBoard v0.7.0</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: monospace;
            background: #1a1a2e;
            color: #eee;
            margin: 0;
            padding: 0;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        h1 { color: #00d4ff; text-align: center; margin: 10px 0; }
        .messages {
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            flex: 1;
            overflow-y: auto;
            margin: 0 20px;
        }
        .message { padding: 8px; border-bottom: 1px solid #333; }
        .message:last-child { border-bottom: none; }
        .time { color: #00d4ff; }
        .commander { color: #ff6b6b; font-weight: bold; }
        .agent { color: #4ecdc4; }
        .result { color: #95e1d3; }
        .input-area {
            display: flex;
            gap: 10px;
            padding: 10px 20px;
        }
        input[type="text"] {
            flex: 1;
            padding: 10px;
            background: #16213e;
            border: 1px solid #00d4ff;
            color: #eee;
            border-radius: 4px;
            font-family: monospace;
        }
        button {
            padding: 10px 20px;
            background: #00d4ff;
            border: none;
            color: #1a1a2e;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
        }
        .info { color: #888; font-size: 12px; text-align: center; padding: 5px; }
    </style>
</head>
<body>
    <h1>SwarmBoard v0.7.0 (FastAPI + Token Auth)</h1>
    <div class="messages" id="messages">
"""

    for msg in recent_messages:
        timestamp = msg.get("timestamp", 0)
        time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
        source = msg.get("source", {})
        model = source.get("model_name", "?")
        role = source.get("role", "?")
        content = msg.get("content", "")

        css_class = "agent"
        if role == "human_commander":
            css_class = "commander"
        elif "[RESULT]" in content:
            css_class = "result"

        content_escaped = (
            content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        html += f'        <div class="message"><span class="time">{time_str}</span> <span class="{css_class}">{model}</span>: {content_escaped}</div>\n'

    html += """    </div>
    <form id="msgForm" class="input-area" onsubmit="sendMessage(event)">
        <input type="text" id="msgInput" placeholder="Type message..." autofocus>
        <button type="submit">Send</button>
    </form>
    <div class="info" id="info">Connecting...</div>
    <script>
        const messagesDiv = document.getElementById('messages');
        const msgInput = document.getElementById('msgInput');
        const infoDiv = document.getElementById('info');
        
        // Get token from URL hash (format: #token=xxx or #xxx)
        let token = null;
        const hash = location.hash.slice(1);
        if (hash.startsWith('token=')) {
            token = hash.replace('token=', '');
        } else if (hash) {
            token = hash; // Direct token without prefix
        }
        
        if (!token) {
            // No token, auto-register
            fetch('/auth/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({instance_id: 'web-commander-' + Date.now(), model_name: 'commander'})
            }).then(r => r.json()).then(data => {
                if (data.token) {
                    token = data.token;
                    location.hash = token;
                    infoDiv.textContent = 'Auto-registered! Token: ' + token.substring(0, 20) + '...';
                }
            }).catch(() => {
                infoDiv.textContent = 'Token required - add ?token=xxx to URL';
            });
        } else {
            infoDiv.textContent = 'Token: ' + token.substring(0, 20) + '... (save this for API)';
        }
        
        function connect() {
            const ws = new WebSocket('ws://' + location.host + '/ws');
            ws.onopen = () => { infoDiv.textContent = 'Connected | v0.7.0'; };
            ws.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.type === 'new_message') addMessage(data.data);
            };
            ws.onclose = () => { setTimeout(connect, 2000); };
            window.ws = ws;
        }
        
        function addMessage(msg) {
            const div = document.createElement('div');
            div.className = 'message';
            const time = new Date(msg.timestamp * 1000).toLocaleTimeString('en-US', {hour12: false});
            const model = msg.source?.model_name || '?';
            let css = 'agent';
            if (msg.source?.role === 'human_commander') css = 'commander';
            else if (msg.content?.includes('[RESULT]')) css = 'result';
            div.innerHTML = '<span class="time">' + time + '</span> <span class="' + css + '">' + model + '</span>: ' + (msg.content || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
        
        function sendMessage(e) {
            e.preventDefault();
            const msg = msgInput.value.trim();
            if (!msg) return;
            fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
                body: JSON.stringify({content: msg})
            }).then(() => { msgInput.value = ''; msgInput.focus(); });
        }
        
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        connect();
        msgInput.focus();
    </script>
</body>
</html>"""

    return HTMLResponse(content=html)


# ================== Main ==================


async def main_async(port: int):
    """Main async function."""
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]

    print(f"Running with hypercorn (Trio)")
    await serve(app, config)


def main():
    parser = argparse.ArgumentParser(description="SwarmBoard v0.7.0 Server")
    parser.add_argument("--port", type=int, default=8080, help="Web port")
    parser.add_argument(
        "--reload", action="store_true", help="Enable live reload (requires uvicorn)"
    )
    args = parser.parse_args()

    print(f"SwarmBoard v{SERVER_VERSION} starting on http://localhost:{args.port}")
    print(f"Swagger docs: http://localhost:{args.port}/docs")
    print(f"[COMMANDER] Web UI: {get_commander_url(args.port)}")

    if args.reload:
        # Use uvicorn for live reload - run directly without import string
        import uvicorn
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent))
        uvicorn.run(
            "scripts.server_v2:app",
            host="0.0.0.0",
            port=args.port,
            reload=True,
            reload_dirs=["scripts"],
        )
    else:
        trio.run(main_async, args.port)


if __name__ == "__main__":
    main()
