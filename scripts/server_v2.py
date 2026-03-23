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
import trio
from hypercorn.config import Config
from hypercorn.trio import serve

SERVER_VERSION = "0.7.0"


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

# Track clients that have called /messages (for welcome message)
seen_clients: set[str] = set()

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


# ================== Auth Endpoints ==================


@app.post("/auth/register")
async def register(auth: AuthRequest):
    """Register and get token."""
    token = create_token(auth.instance_id)
    tokens[token] = {
        "instance_id": auth.instance_id,
        "model_name": auth.model_name,
        "role": auth.role,
        "created_at": time.time(),
    }
    return {"token": token, "instance_id": auth.instance_id}


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
    client: dict = Depends(get_current_client),
):
    """Get messages filtered by session/room/since."""
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

    # Filter by since (timestamp)
    if since:
        filtered = [m for m in filtered if m.get("timestamp", 0) > since]

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
    # Handle commands
    if message.content.startswith("/"):
        return await handle_command(message.content, client)

    # Create message
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
        "room": message.room or "lobby",
    }

    messages.append(msg)

    # Add to room
    room_name = message.room or "lobby"
    if room_name in rooms:
        rooms[room_name]["messages"].append(msg)

    # Broadcast to WebSocket clients
    await broadcast_message(msg)

    return {"status": "ok", "msg_id": msg["msg_id"]}


async def handle_command(content: str, client: dict) -> dict:
    """Handle slash commands."""
    global current_session_id, messages, rooms, sessions, tokens
    cmd = content.split()[0].lower()

    if cmd == "/help":
        return {
            "status": "ok",
            "response": "Commands: /help, /status, /new-session, /rooms, /create <name>, /join <name>, /leave",
        }

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
        return {"status": "ok", "response": f"Joined room '{room_name}'"}

    elif cmd == "/leave":
        return {"status": "ok", "response": "Left room"}

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
    return {
        "version": "0.7.0",
        "session": current_session_id,
        "messages": len(messages),
        "rooms": len(rooms),
        "connected_clients": len(tokens),
        "ws_clients": len(ws_clients),
    }


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
