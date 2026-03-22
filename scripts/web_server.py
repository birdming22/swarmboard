#!/usr/bin/env python3
"""
SwarmBoard Web UI - WebSocket-based web interface for Commander.

Usage:
    uv run python scripts/web_server.py [--port 8080] [--router tcp://127.0.0.1:5570] [--pub tcp://127.0.0.1:5571]
"""

import argparse
import asyncio
import json
import time
import zmq
import zmq.asyncio
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="SwarmBoard Web UI")

# Global state
router_addr = "tcp://127.0.0.1:5570"
pub_addr = "tcp://127.0.0.1:5571"
ctx = zmq.asyncio.Context()

# Connected WebSocket clients
connected_clients: list[WebSocket] = []


def read_blackboard():
    """Read blackboard from server."""
    sync_ctx = zmq.Context()
    dealer = sync_ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, f"web-reader-{int(time.time()) % 10000}")
    dealer.connect(router_addr)
    dealer.setsockopt(zmq.RCVTIMEO, 3000)

    read_req = {
        "msg_id": f"msg-{int(time.time())}",
        "timestamp": int(time.time()),
        "source": {
            "instance_id": "web-reader",
            "model_name": "web",
            "role": "reader",
        },
        "action": "READ_REQUEST",
        "content": "",
    }

    try:
        dealer.send_string(json.dumps(read_req, ensure_ascii=False))
        reply = dealer.recv_string()
        msg = json.loads(reply)
        if msg.get("action") == "READ_RESPONSE":
            messages = json.loads(msg.get("content", "[]"))
            return messages
    except Exception:
        pass
    finally:
        dealer.close()
        sync_ctx.term()

    return []


def send_message(content):
    """Send message to blackboard."""
    sync_ctx = zmq.Context()
    dealer = sync_ctx.socket(zmq.DEALER)
    dealer.setsockopt_string(zmq.IDENTITY, f"web-commander-{int(time.time()) % 10000}")
    dealer.connect(router_addr)
    dealer.setsockopt(zmq.RCVTIMEO, 3000)

    msg = {
        "msg_id": f"msg-{int(time.time())}",
        "timestamp": int(time.time()),
        "source": {
            "instance_id": "web-commander",
            "model_name": "commander",
            "role": "human_commander",
        },
        "action": "WRITE",
        "content": f"[COMMANDER] {content}",
    }

    try:
        dealer.send_string(json.dumps(msg, ensure_ascii=False))
        dealer.recv_string()  # ACK
        return True
    except Exception:
        return False
    finally:
        dealer.close()
        sync_ctx.term()


async def broadcast_to_clients(message: dict):
    """Broadcast message to all connected WebSocket clients."""
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)


async def zmq_subscriber():
    """Subscribe to ZMQ PUB and broadcast to WebSocket clients."""
    sub = ctx.socket(zmq.SUB)
    sub.connect(pub_addr)
    sub.setsockopt_string(zmq.SUBSCRIBE, "blackboard")
    sub.setsockopt(zmq.RCVTIMEO, 1000)

    while True:
        try:
            topic = await sub.recv_string()
            data = await sub.recv_string()
            msg = json.loads(data)
            if msg.get("action") == "STATE_UPDATE":
                content = msg.get("content", "")
                try:
                    entry = json.loads(content)
                    await broadcast_to_clients({"type": "new_message", "data": entry})
                except Exception:
                    pass
        except zmq.Again:
            await asyncio.sleep(0.1)
        except Exception:
            await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event():
    """Start ZMQ subscriber on startup."""
    asyncio.create_task(zmq_subscriber())


@app.get("/", response_class=HTMLResponse)
async def home():
    """Main page with WebSocket support."""
    messages = read_blackboard()

    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>SwarmBoard</title>
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
        h1 {
            color: #00d4ff;
            text-align: center;
            margin: 10px 0;
            flex-shrink: 0;
        }
        .messages {
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            flex: 1;
            overflow-y: auto;
            margin: 0 20px;
        }
        .message {
            padding: 8px;
            border-bottom: 1px solid #333;
        }
        .message:last-child {
            border-bottom: none;
        }
        .time {
            color: #00d4ff;
        }
        .commander {
            color: #ff6b6b;
            font-weight: bold;
        }
        .agent {
            color: #4ecdc4;
        }
        .result {
            color: #95e1d3;
        }
        .status {
            color: #f38181;
        }
        .input-area {
            display: flex;
            gap: 10px;
            padding: 10px 20px;
            flex-shrink: 0;
        }
        input[type="text"] {
            flex: 1;
            padding: 10px;
            background: #16213e;
            border: 1px solid #00d4ff;
            color: #eee;
            border-radius: 4px;
            font-family: monospace;
            font-size: 14px;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #00a8cc;
        }
        button {
            padding: 10px 20px;
            background: #00d4ff;
            border: none;
            color: #1a1a2e;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
            font-size: 14px;
        }
        button:hover {
            background: #00a8cc;
        }
        .info {
            color: #888;
            font-size: 12px;
            text-align: center;
            padding: 5px;
            flex-shrink: 0;
        }
    </style>
</head>
<body>
    <h1>SwarmBoard</h1>
    <div class="messages" id="messages">
"""

    for msg in messages[-50:]:
        html += render_message(msg)

    html += (
        """    </div>
    <form id="msgForm" class="input-area" onsubmit="sendMessage(event)">
        <input type="text" id="msgInput" placeholder="Type message..." autofocus>
        <button type="submit">Send</button>
    </form>
    <div class="info" id="info">Connecting... | Messages: """
        + str(len(messages))
        + """</div>
    <script>
        const messagesDiv = document.getElementById('messages');
        const msgInput = document.getElementById('msgInput');
        const infoDiv = document.getElementById('info');
        let ws = null;
        let msgCount = """
        + str(len(messages))
        + """;

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(protocol + '//' + location.host + '/ws');

            ws.onopen = function() {
                infoDiv.textContent = 'Connected | Messages: ' + msgCount;
            };

            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.type === 'new_message') {
                    addMessage(data.data);
                    msgCount++;
                    infoDiv.textContent = 'Connected | Messages: ' + msgCount;
                }
            };

            ws.onclose = function() {
                infoDiv.textContent = 'Disconnected. Reconnecting...';
                setTimeout(connect, 2000);
            };

            ws.onerror = function() {
                ws.close();
            };
        }

        function addMessage(msg) {
            const div = document.createElement('div');
            div.className = 'message';

            const time = new Date(msg.timestamp * 1000).toLocaleTimeString('en-US', {hour12: false});
            const source = msg.source || {};
            const model = source.model_name || '?';
            const role = source.role || '?';
            const content = msg.content || '';

            let cssClass = 'agent';
            if (role === 'human_commander') cssClass = 'commander';
            else if (content.includes('[RESULT]')) cssClass = 'result';
            else if (content.includes('[STATUS]')) cssClass = 'status';

            div.innerHTML = '<span class="time">' + time + '</span> <span class="' + cssClass + '">' + model + '</span>: ' + escapeHtml(content);

            messagesDiv.appendChild(div);

            // Auto-scroll to bottom
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function sendMessage(event) {
            event.preventDefault();
            const message = msgInput.value.trim();
            if (!message) return;

            fetch('/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: message})
            }).then(() => {
                msgInput.value = '';
                msgInput.focus();
            });

            return false;
        }

        // Auto-scroll on load
        messagesDiv.scrollTop = messagesDiv.scrollHeight;

        // Connect WebSocket
        connect();

        // Keep focus on input
        msgInput.focus();
    </script>
</body>
</html>"""
    )

    return HTMLResponse(content=html)


def render_message(msg):
    """Render a single message as HTML."""
    timestamp = msg.get("timestamp", 0)
    time_str = time.strftime("%H:%M:%S", time.localtime(timestamp))
    source = msg.get("source", {})
    model = source.get("model_name", "?")
    role = source.get("role", "?")
    content = msg.get("content", "")

    if role == "human_commander":
        css_class = "commander"
    elif "[RESULT]" in content:
        css_class = "result"
    elif "[STATUS]" in content:
        css_class = "status"
    else:
        css_class = "agent"

    # Escape HTML
    content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f'        <div class="message"><span class="time">{time_str}</span> <span class="{css_class}">{model}</span>: {content}</div>\n'


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


@app.post("/send")
async def send(request: Request):
    """Send message via JSON."""
    data = await request.json()
    message = data.get("message", "")
    if message.strip():
        send_message(message.strip())
    return {"status": "ok"}


def main():
    global router_addr, pub_addr

    parser = argparse.ArgumentParser(description="SwarmBoard Web UI")
    parser.add_argument("--port", type=int, default=8080, help="Web port")
    parser.add_argument(
        "--router", default="tcp://127.0.0.1:5570", help="ROUTER endpoint"
    )
    parser.add_argument("--pub", default="tcp://127.0.0.1:5571", help="PUB endpoint")
    args = parser.parse_args()

    router_addr = args.router
    pub_addr = args.pub

    print(f"SwarmBoard Web UI starting on http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
