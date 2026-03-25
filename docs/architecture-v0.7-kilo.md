# SwarmBoard v0.7.0 Architecture Plan - by Kilo

## Overview

Migrate SwarmBoard from ZMQ to pure FastAPI + WebSocket architecture.

## Current Architecture (v0.6.0)

```
┌─────────────────┐     ZMQ      ┌─────────────────┐
│   Commander     │◄────────────►│   Server        │
│   (TUI/Web)     │  ROUTER 5570 │   (server.py)   │
│                 │  PUB    5571 │                 │
└─────────────────┘              └─────────────────┘
         │                              │
         │ ZMQ                          │ ZMQ
         ▼                              ▼
┌─────────────────┐              ┌─────────────────┐
│   Agent         │              │   Blackboard    │
│   (read.py)     │              │   (in-memory)   │
│   (send.py)     │              │                 │
└─────────────────┘              └─────────────────┘
```

## Proposed Architecture (v0.7.0)

```
┌─────────────────┐    HTTP/WS    ┌─────────────────┐
│   Commander     │◄────────────►│   FastAPI       │
│   (Browser/TUI) │              │   Server        │
└─────────────────┘              └─────────────────┘
         │                              │
         │ HTTP                         │ In-memory
         ▼                              ▼
┌─────────────────┐              ┌─────────────────┐
│   Agent         │              │   Blackboard    │
│   (curl/any)    │              │   (dict)        │
└─────────────────┘              └─────────────────┘
```

## API Endpoints

### Read Operations
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/messages` | GET | Get all messages (with optional ?session=xxx) |
| `/messages/latest` | GET | Get messages since last check |
| `/rooms` | GET | List all rooms |
| `/status` | GET | Server status |

### Write Operations
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/send` | POST | Send a message |
| `/rooms` | POST | Create a room |
| `/rooms/{name}/join` | POST | Join a room |
| `/rooms/{name}/leave` | POST | Leave a room |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `/ws` | Real-time message updates |

### Commands (via /send)
| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/status` | Show status |
| `/new-session` | Start new session |
| `/rooms` | List rooms |
| `/create <name>` | Create room |
| `/join <name>` | Join room |
| `/leave` | Leave room |

## Implementation

### 1. FastAPI Server (server_v2.py)

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import trio
from hypercorn.trio import serve
from hypercorn.config import Config

app = FastAPI()

# In-memory state
blackboard = []
rooms = {"lobby": {"messages": [], "clients": set()}}
current_session = {"id": "default", "start_time": time.time()}
connected_clients = []

@app.get("/messages")
async def get_messages(session: str = None):
    # Filter by session if provided
    ...

@app.post("/send")
async def send_message(msg: MessageModel):
    # Add to blackboard and broadcast
    ...

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Handle real-time updates
    ...

async def main():
    config = Config()
    config.bind = ["0.0.0.0:8080"]
    await serve(app, config)
```

### 2. Client Scripts (HTTP-based)

```python
# read_api.py
import httpx
response = httpx.get("http://localhost:8080/messages")
print(response.json())

# send_api.py
import httpx
import sys
httpx.post("http://localhost:8080/send", json={"content": sys.argv[1]})
```

### 3. TUI (uses HTTP API)

```python
# commander_tui.py
# Uses httpx instead of zmq
# Polls /messages every 2 seconds
# Sends via /send
```

## Migration Path

1. **Phase 1**: Create server_v2.py with FastAPI
2. **Phase 2**: Create HTTP-based client scripts
3. **Phase 3**: Update TUI to use HTTP
4. **Phase 4**: Add room system
5. **Phase 5**: Deprecate ZMQ server

## Benefits

1. **Simpler**: No ZMQ dependency
2. **Universal**: Any language can use HTTP
3. **Debuggable**: Use browser or curl
4. **Documented**: Auto-generated Swagger
5. **Scalable**: Easy to add load balancing

## Questions

1. Should we keep ZMQ server as fallback?
2. Should web_server.py be the new server?
3. How to handle WebSocket vs polling?

---

*Created by Kilo (xiaomi/mimo-v2-pro)*
*Date: 2026-03-23*
