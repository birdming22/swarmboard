# SwarmBoard — Implementation Plan

> **Date**: 2026-03-21
> **Status**: Implementing V1
> **Scope**: 共用黑板系統，支援多個 AI CLI Instance 並行寫入與廣播，以 ZeroMQ 作為通訊底層
> **Toolchain**: Python 3.12 + pyzmq, managed by `uv`

---

## 1. 系統架構總覽

系統採用 **Client-Server 拓樸**。

- **Blackboard Server (Hub):** 唯一事實來源 (Single Source of Truth)，維護黑板歷史紀錄（記憶體 List），序列化所有寫入請求。
- **AI CLI Clients (Contributors):** 各自掛載不同模型的獨立進程。啟動時生成 UUID 作為 `instance_id`。
- **Human CLI Client (Commander):** 人類的終端機介面，下達初始任務、監聽所有動態、必要時寫入指令。

```
                          ┌───────────────────────────────────────┐
                          │        Blackboard Server (Hub)        │
                          │                                       │
  AI CLI ── DEALER ───────┤  Port A: ROUTER  (Write/Query)       │
  AI CLI ── DEALER ───────┤    action: WRITE / READ_REQUEST      │
  AI CLI ── DEALER ───────┤                                       │
                          │  Port B: PUB     (Broadcast)          │
  AI CLI ──── SUB  ◄──────┤    新訊息 append → broadcast          │
  Human ───── SUB  ◄──────┤                                       │
  Human ─── DEALER ───────┤                                       │
                          └───────────────────────────────────────┘
```

---

## 2. ZMQ 通訊拓樸

| Port | Socket Type | Server Side | Client Side | 用途 |
|------|-------------|-------------|-------------|------|
| `5570` | ROUTER / DEALER | ROUTER | DEALER | 寫入黑板 (WRITE)、讀取完整黑板 (READ_REQUEST) |
| `5571` | PUB / SUB | PUB | SUB | 黑板內容變更時廣播給所有訂閱者 |

### 混合模式設計

- **ROUTER / DEALER (Port A):** Server 端 ROUTER 原生支援多路復用，能識別並隔離不同 Client，處理完後精準回覆。Client 端 DEALER 不會像 REQ/REP 那樣發生死鎖。
- **PUB / SUB (Port B):** Server 端 PUB 每當黑板有新內容寫入成功時，主動廣播給所有連線的 Client。Client 端 SUB 不需要輪詢，有寫入即時收到通知。

---

## 3. 識別碼與資料規格

### 3.1 實體識別 (Entity Identification)

每個 CLI Instance 啟動時，Payload 中夾帶：

| 欄位 | 型態 | 說明 |
|------|------|------|
| `instance_id` | `str` | UUID 或隨機字串 (例: `cli-qwen-8f3a`)，確保同模型多開也能區分 |
| `model_name` | `str` | 底層模型名 (例: `qwen-2.5-coder`, `claude-3.5-sonnet`) |
| `role` | `str` | 角色定義: `ai_agent`, `human_commander` |

### 3.2 核心訊息結構 (Message Schema)

```json
{
  "msg_id": "msg-5b9c-...",
  "timestamp": 1711036800,
  "source": {
    "instance_id": "cli-qwen-8f3a",
    "model_name": "qwen-2.5-coder",
    "role": "ai_agent"
  },
  "action": "WRITE",
  "content": "建議使用 ZMQ_CONFLATE 來解決掉包問題..."
}
```

**Action 值定義:**

| Action | 方向 | 說明 |
|--------|------|------|
| `WRITE` | Client → Server | 寫入一筆新訊息到黑板 |
| `READ_REQUEST` | Client → Server | 請求完整的黑板歷史紀錄 |
| `READ_RESPONSE` | Server → Client | 回覆完整黑板歷史紀錄 |
| `STATE_UPDATE` | Server → Client (PUB) | 廣播：黑板有新內容 append |

---

## 4. 工作流程

### 4.1 CLI Instance 初始化與同步

1. 新的 AI CLI 啟動（生成獨立 `instance_id`）。
2. CLI 透過 DEALER socket 發送 `action: "READ_REQUEST"` 給 Server。
3. Server 的 ROUTER 收到後，將當前黑板完整歷史紀錄（List）回傳給該 `instance_id`。
4. CLI 同步完畢，開始透過 SUB socket 監聽未來的廣播。

### 4.2 並發寫入與防衝突

1. `instance-A` 和 `instance-B` 同時對同一問題產生解答。
2. 兩者同時透過 DEALER socket 發送 `action: "WRITE"`。
3. Server 底層 Event Loop 將接收到的訊息序列化（Queue 化），依序 Append。
4. Server 每 Append 一筆，立刻透過 PUB socket 廣播該筆 Message Object。

### 4.3 人類的發起與觀測

1. 人類 CLI 啟動（`role: human_commander`）。
2. 終端機畫面上，由 SUB socket 印出各 AI CLI 寫入黑板的內容。有 `instance_id` 可見來源。
3. 人類發現方向偏了，直接在終端機輸入指令。指令透過 DEALER 送給 Server，Server 再透過 PUB 廣播給所有 AI。

---

## 5. 檔案結構

```
swarmboard/
├── pyproject.toml          # uv project config, pyzmq dependency
├── src/
│   └── swarmboard/
│       ├── __init__.py
│       ├── protocol.py     # 共用: Message schema, Action enum, 訊息建構/解析
│       ├── server.py       # Blackboard Server (ROUTER+PUB)
│       ├── client.py       # AI Agent Client (DEALER+SUB)
│       └── commander.py    # Human Commander Client (DEALER+SUB, 互動式)
└── tests/
    └── test_end_to_end.py  # 端到端整合測試
```

---

## 6. 實作階段

### Phase 0: 專案初始化 (`uv init`)

- `uv init swarmboard`
- `uv add pyzmq`
- 建立 `src/swarmboard/` package 結構

### Phase 1: protocol.py — 共用協議

- `Action` enum: WRITE, READ_REQUEST, READ_RESPONSE, STATE_UPDATE
- `make_msg(source, action, content)` → 產生標準 Message dict
- `parse_msg(raw_json)` → 解析 + 驗證，失敗回傳 None
- `make_source(instance_id, model_name, role)` → 建立 source dict

### Phase 2: server.py — Blackboard Server

- `ROUTER` socket 綁定 Port 5570，處理 WRITE / READ_REQUEST
- `PUB` socket 綁定 Port 5571，每次 append 後廣播 STATE_UPDATE
- 記憶體黑板: `List[dict]`，每筆為完整 Message object
- `zmq.Poller` event loop，同時監聽 ROUTER
- 信號處理 (SIGINT/SIGTERM) 乾淨關閉

### Phase 3: client.py — AI Agent Client

- `DEALER` socket 連線 Port 5570，發送 WRITE / READ_REQUEST
- `SUB` socket 連線 Port 5571，訂閱廣播
- 啟動時自動 READ_REQUEST → 同步歷史
- 提供 `write(content)` 方法
- `zmq.Poller` event loop + callback hook

### Phase 4: commander.py — Human Commander CLI

- 同 client.py 的 DEALER + SUB
- 互動式終端機：SUB 的廣播即時印出（含 instance_id 標籤）
- 人類輸入一行文字 → WRITE 到黑板
- `asyncio` 或 threading 讓輸入與廣播同時運作

### Phase 5: 端到端測試

- 啟動 Server → 啟動 2 個 AI Client + 1 個 Commander
- 驗證: 初始化同步、並發寫入、廣播接收、人類指令

---

## 7. 設計優勢

- **極致解耦:** CLI 死掉/重開/中途加入不影響黑板運作，不遺失歷史。
- **絕對識別:** 透過 `instance_id`，未來可擴充如「請 `cli-qwen-8f3a` 針對這個函數重寫，其他暫停」。
- **無鎖並發:** ZMQ 機制完全不需要 Thread Lock / Mutex，Server 端單線程處理 ROUTER 即可應付高吞吐。

---

## 8. V1 驗收標準

- [ ] `uv run swarmboard-server` 啟動成功，綁定兩個 port
- [ ] `uv run swarmboard-client --model test-model` 啟動 → 自動同步 → 可寫入
- [ ] `uv run swarmboard-commander` 啟動 → 看到廣播 → 可輸入指令
- [ ] 2 個 Client 同時 WRITE，Server 序列化 append，所有 SUB 收到
- [ ] 乾淨關閉 (Ctrl+C)，無 orphan process
