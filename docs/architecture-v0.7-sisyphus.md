# SwarmBoard v0.7.0 Architecture Plan - by Sisyphus

## Overview

基於現有 web_server.py 進行擴展，新增 HTTP API + Token Auth + Room 系統。

## 與 Kilo 版本的差異

| 面向 | Kilo 版本 | Sisyphus 版本 |
|------|-----------|---------------|
| 伺服器 | 新建 server_v2.py | 擴展 web_server.py |
| ZMQ | 完全移除 | 保留作為可選 |
| Auth | 無 | Token-based |
| 架構 | 所有功能在同一處 | API / Core / Storage 分層 |

## 目標架構 (v0.7.0)

```
┌─────────────────────────────────────────────────────────────┐
│                     Client Layer                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │  TUI     │  │  Web     │  │  curl    │  │  Agent   │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
└───────┼──────────────┼──────────────┼──────────────┼──────────┘
        │              │              │              │
        ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /messages (GET/POST)  /rooms (GET/POST)            │   │
│  │  /send (POST)           /join/:room (POST)           │   │
│  │  /auth/login (POST)     /auth/verify (GET)          │   │
│  │  /ws (WebSocket)        /docs (Swagger)            │   │
│  └─────────────────────────────────────────────────────┘   │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  Auth Service│   │ Room Service  │   │  Core Service │
│  - login()   │   │ - create()    │   │ - read()      │
│  - verify()  │   │ - join()      │   │ - write()     │
│  - gen_token │   │ - leave()     │   │ - broadcast() │
└───────────────┘   └───────────────┘   └───────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │    Storage Layer        │
              │  - blackboard (list)    │
              │  - rooms (dict)         │
              │  - sessions (dict)      │
              │  - tokens (dict)       │
              └─────────────────────────┘
```

## API Endpoints

### 1. 認證 (Auth)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | 登入並取得 token |
| `/auth/verify` | GET | 驗證 token 是否有效 |
| `/auth/logout` | POST | 登出並使 token 失效 |

**Request/Response:**
```python
# POST /auth/login
Request: {"username": "commander", "password": "xxx"}
Response: {"token": "eyJxxx...", "expires_in": 3600}

# GET /auth/verify
Headers: Authorization: Bearer <token>
Response: {"valid": true, "username": "commander", "role": "commander"}
```

### 2. 訊息 (Messages)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/messages` | GET | 取得所有訊息 |
| `/messages` | POST | 發送訊息 |
| `/messages/latest` | GET | 取得最新訊息 |
| `/messages/:id` | GET | 取得特定訊息 |

### 3. 房間 (Rooms)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/rooms` | GET | 列出所有房間 |
| `/rooms` | POST | 建立新房間 |
| `/rooms/:name` | GET | 取得房間資訊 |
| `/rooms/:name/join` | POST | 加入房間 |
| `/rooms/:name/leave` | POST | 離開房間 |

### 4. 即時通訊 (Real-time)
| Endpoint | Description |
|----------|-------------|
| `/ws` | WebSocket 即時更新 |
| `/ws/rooms/:name` | 房間專用 WebSocket |

### 5. 系統 (System)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | 伺服器狀態 |
| `/sessions` | GET | 已註冊的會話 |
| `/health` | GET | 健康檢查 |

## Token Auth 流程

```
1. Client 發送 POST /auth/login
2. Server 驗證 username/password
3. Server 生成 JWT token (包含 role, exp)
4. Client 在後續請求中帶 Authorization: Bearer <token>
5. Server 在 middleware 中驗證 token
6. 驗證通過才允許訪問 API
```

**Token 內容:**
```python
{
    "sub": "instance_id",
    "username": "commander",
    "role": "commander",  # commander | agent
    "exp": 1774233600    # 過期時間
}
```

**Middleware 權限:**
| 角色 | /messages | /send | /rooms | /auth |
|------|-----------|-------|--------|-------|
| commander | ✓ | ✓ | ✓ | ✓ |
| agent | ✓ (自己的) | ✓ | ✓ | ✗ |
| anonymous | ✗ | ✗ | ✓ | ✓ (login only) |

## Room 系統

### 預設房間
- `lobby` - 預設大廳，所有人都在

### 房間狀態
```python
{
    "name": "room_name",
    "created_at": 1774233000,
    "members": ["instance_id_1", "instance_id_2"],
    "message_count": 42
}
```

### 使用流程
```
1. Agent 啟動 → 自動加入 lobby
2. @mention 觸發 → 在 lobby 處理
3. /create <name> → 建立新房間
4. /join <name> → 加入房間
5. /leave → 離開當前房間，回 lobby
```

## ZMQ 保持相容

**為什麼保留 ZMQ:**
1. 現有 Agent 使用 ZMQ (send.py, read.py)
2. 逐步遷移，避免一次大改動
3. ZMQ 效能較低延遲

**實現方式:**
```python
# web_server.py 中的 hybrid 模式
if USE_ZMQ:
    # 繼續處理 ZMQ 請求
    zmq_handler.process(message)

# 新的 HTTP 請求
api_handler.process(request)
```

## 實作順序

### Phase 1: 基礎設施 (1-2 days)
1. 擴展 web_server.py HTTP API
2. 新增 /messages, /rooms 端點
3. 新增 token auth 中間件

### Phase 2: Room 系統 (1-2 days)
1. 房間 CRUD API
2. 房間成員管理
3. 訊息過濾 (只看自己房間)

### Phase 3: Client 遷移 (1-2 days)
1. 更新 send.py 支援 --http 模式
2. 更新 read.py 支援 --http 模式
3. 更新 commander_tui.py 使用 HTTP

### Phase 4: 清理 (1 day)
1. 標記 ZMQ 為 deprecated
2. 更新文件
3. 移除多餘依賴

## 檔案變更

| 檔案 | 變更 |
|------|------|
| `scripts/web_server.py` | 大幅擴展，新增 API + Auth |
| `scripts/send.py` | 新增 --http 模式 |
| `scripts/read.py` | 新增 --http 模式 |
| `scripts/commander_tui.py` | 改用 HTTP |
| `swarmboard/protocol.py` | 新增 Token model |
| `docs/architecture-v0.7.md` | 本檔案 |

## 優點

1. **漸進遷移** - 現有 ZMQ client 仍可用
2. **Token Auth** - Commander 要求的認證機制
3. **分層設計** - API / Core / Storage 分開
4. **相容 Swagger** - 自動 API 文件
5. **WebSocket** - 即時推播

## 問題

1. Token 過期處理？→ Refresh token
2. 多重登入？→ Token 黑名單
3. 房間訊息隔離？→ 每個房間獨立的 message list

---

*Created by Sisyphus (minimax-m2.5-free)*
*Date: 2026-03-23*