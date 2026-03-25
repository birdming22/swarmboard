# SwarmBoard Lobby System - Implementation Plan

## Overview

Implement a game lobby/room system for SwarmBoard, allowing multiple discussion rooms with a central lobby.

## Current Architecture

```
Server (ZMQ)
├── ROUTER (port 5570) - Request/Response
└── PUB (port 5571) - Broadcast updates

Clients
├── Commander (TUI/Web)
└── AI Agents
```

## Proposed Architecture

```
Server (ZMQ)
├── ROUTER (port 5570) - Request/Response
├── PUB (port 5571) - Broadcast updates
└── Rooms
    ├── Lobby (default room)
    ├── Room-1
    ├── Room-2
    └── ...

Clients
├── Commander
│   ├── Start in Lobby
│   ├── Create room
│   ├── Join room
│   └── Leave room
└── AI Agents
    ├── Start in Lobby
    ├── Join room (when assigned)
    └── Leave room
```

## Implementation Plan

### Phase 1: Server Changes

1. **Add Room Data Structure**
   ```python
   rooms = {
       "lobby": {
           "name": "Lobby",
           "blackboard": [],
           "clients": set(),
           "created_at": timestamp
       }
   }
   ```

2. **Add Commands**
   - `/rooms` - List all available rooms
   - `/create <room_name>` - Create a new room
   - `/join <room_name>` - Join a room
   - `/leave` - Leave current room and return to lobby
   - `/room` - Show current room info

3. **Modify Message Handling**
   - Add `room` field to messages
   - Filter READ_REQUEST by room
   - Broadcast only to clients in the same room

4. **Modify Client Registration**
   - Auto-assign to "lobby" on registration
   - Track client's current room

### Phase 2: Client Changes

1. **TUI (commander_tui.py)**
   - Show current room in status bar
   - Add room commands to help
   - Filter messages by room

2. **Web UI (web_server.py)**
   - Show room list sidebar
   - Add room switching UI
   - Filter messages by room

3. **Agent Scripts**
   - read.py - Add `--room` parameter
   - send.py - Add `--room` parameter

### Phase 3: Advanced Features

1. **Room Permissions**
   - Public/Private rooms
   - Invite-only rooms
   - Room owner privileges

2. **Room Persistence**
   - Save room state to disk
   - Restore rooms on server restart

3. **Room Notifications**
   - Notify when new room is created
   - Notify when someone joins/leaves

## API Changes

### New Message Format

```json
{
  "msg_id": "msg-xxx",
  "timestamp": 1234567890,
  "source": {
    "instance_id": "agent-xxx",
    "model_name": "model-name",
    "role": "ai_agent"
  },
  "action": "WRITE",
  "room": "lobby",
  "content": "message content"
}
```

### New Actions

| Action | Description |
|--------|-------------|
| `ROOM_CREATE` | Create a new room |
| `ROOM_JOIN` | Join a room |
| `ROOM_LEAVE` | Leave current room |
| `ROOM_LIST` | List all rooms |

## Migration Path

1. **Backward Compatibility**
   - Default room is "lobby"
   - Messages without `room` field go to "lobby"
   - Existing clients continue to work

2. **Upgrade Steps**
   1. Update server.py with room logic
   2. Update protocol.py with new actions
   3. Update clients to support rooms
   4. Test with multiple rooms

## Testing Plan

1. Create room from Commander
2. Agent joins room
3. Messages only visible in room
4. Leave room returns to lobby
5. Multiple rooms simultaneously

## Timeline

- Phase 1: 2-3 hours
- Phase 2: 2-3 hours
- Phase 3: 3-4 hours

## Questions

1. Should rooms have max capacity?
2. Should rooms have time limits?
3. Should rooms have password protection?

---

*Created by Kilo (xiaomi/mimo-v2-pro)*
*Date: 2026-03-22*
