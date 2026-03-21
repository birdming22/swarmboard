# SwarmBoard — 實施報告

> **Date**: 2026-03-21
> **Version**: 0.1.0 (V1)
> **Status**: Implementation Complete — All tests passed

---

## 1. 專案概述

SwarmBoard 是一個基於 ZeroMQ 的非同步訊息代理系統，為多個 AI CLI Instance 提供共用黑板機制。各 Instance 可並行寫入想法與程式碼片段，透過 Server 端序列化避免衝突，並經由 PUB/SUB 廣播讓所有參與者即時接收更新。

### 核心解決的問題

- 多個 AI CLI（不同模型、同模型多開）需要共享上下文
- 傳統 HTTP/REST 的輪詢 (Polling) 開銷過高
- 並發寫入需要序列化，但不想引入複雜的分散式鎖機制
- 每個 CLI Instance 必須有獨立可識別的 ID

---

## 2. 技術架構

### 2.1 拓樸結構

```
                          ┌───────────────────────────────────────┐
                          │        Blackboard Server (Hub)        │
                          │                                       │
  AI CLI ── DEALER ───────┤  Port A: ROUTER  (Write/Query)       │
  AI CLI ── DEALER ───────┤    5570                               │
                          │                                       │
                          │  Port B: PUB     (Broadcast)          │
  AI CLI ──── SUB  ◄──────┤    5571                               │
  Human ───── SUB  ◄──────┤                                       │
  Human ─── DEALER ───────┤                                       │
                          └───────────────────────────────────────┘
```

### 2.2 Socket 模式選擇

| Socket | 角色 | 綁定端 | 說明 |
|--------|------|--------|------|
| `ROUTER` | Server | Port 5570 | 原生多路復用，自動識別不同 Client 的 `IDENTITY`，處理後精準回覆 |
| `PUB` | Server | Port 5571 | 黑板有新寫入時，廣播 `STATE_UPDATE` 給所有訂閱者 |
| `DEALER` | Client | — | 非同步請求，不像 REQ/REP 會發生死鎖 (Deadlock) |
| `SUB` | Client | — | 訂閱 `blackboard` topic，被動接收廣播，無需輪詢 |

### 2.3 通訊協議

所有傳輸的 Payload 採用 JSON 格式，統一的 Message Schema：

```json
{
    "msg_id": "msg-<uuid4 hex>",
    "timestamp": <unix_epoch_seconds>,
    "source": {
        "instance_id": "cli-qwen-8f3a",
        "model_name": "qwen-2.5-coder",
        "role": "ai_agent"
    },
    "action": "WRITE",
    "content": "訊息內容"
}
```

**Action 類型:**

| Action | 方向 | 用途 |
|--------|------|------|
| `WRITE` | Client → Server | 寫入一筆新訊息到黑板 |
| `READ_REQUEST` | Client → Server | 請求完整黑板歷史 |
| `READ_RESPONSE` | Server → Client | 回覆完整黑板歷史（JSON 序列化的 List） |
| `STATE_UPDATE` | Server → Client (PUB) | 廣播：黑板有新內容，payload 為該筆 entry |

---

## 3. 檔案結構

```
swarmboard/
├── pyproject.toml                          # uv 專案配置
├── src/swarmboard/
│   ├── __init__.py
│   ├── protocol.py    (63 lines)           # 共用協議：Action enum, Message 建構/解析
│   ├── server.py      (170 lines)          # Blackboard Server
│   ├── client.py      (181 lines)          # AI Agent Client
│   └── commander.py   (168 lines)          # Human Commander Client
├── tests/
│   └── test_end_to_end.py (227 lines)      # 端到端整合測試
└── .venv/                                  # uv 虛擬環境
```

**總程式碼量**: 809 行 Python（不含 .venv）

---

## 4. 實作細節

### 4.1 protocol.py — 共用協議層

| 函式 | 用途 |
|------|------|
| `make_source(instance_id, model_name, role)` | 建立 source dict |
| `make_msg(source, action, content)` | 建立標準 Message，自動產生 `msg_id` 和 `timestamp` |
| `encode_msg(msg)` | JSON 序列化，`ensure_ascii=False` |
| `decode_msg(raw)` | JSON 反序列化 + 基本驗證，失敗回傳 `None` |

`Action` 為 `str, Enum` 雙繼承，可直接用 `.value` 取字串。

### 4.2 server.py — Server 實作

**初始化流程:**
1. 解析參數（`--router-bind`, `--pub-bind`）
2. 註冊 `SIGINT` / `SIGTERM` 信號處理
3. 建立 `zmq.Context`
4. 綁定 ROUTER socket（Port 5570）
5. 綁定 PUB socket（Port 5571）
6. 初始化記憶體黑板 `list[dict]`

**主迴圈 (`zmq.Poller`, timeout=500ms):**

```
Poller 等待 ROUTER 可讀
  ├─ READ_REQUEST → 回傳 blackboard 完整 List
  ├─ WRITE → append 到 blackboard → ACK 回覆 writer → PUB 廣播 STATE_UPDATE
  └─ 未知 action → log 警告
```

**關鍵設計決定:**

- `frames[-1]` 取 payload：兼容 DEALER 發送的 2-frame 格式（`[identity, payload]`）與可能的 3-frame 格式
- ROUTER 回覆使用 2-frame（`[client_id, payload]`），不插入空 delimiter
- 廣播 topic 固定為 `"blackboard"`，使用 `SNDMORE` flag

**關閉流程:**
- 信號觸發 → `running = False` → 跳出主迴圈 → close sockets → term context

### 4.3 client.py — AI Agent Client 實作

**初始化流程:**
1. 解析參數（`--model`, `--instance-id`, `--router`, `--pub`）
2. 自動生成 `instance_id`：格式 `cli-{model}-{uuid4[:4]}`
3. 建立 DEALER socket，設定 `IDENTITY` 為 `instance_id`
4. 建立 SUB socket，訂閱 `"blackboard"` topic

**同步階段 (Phase 1):**
- 發送 `READ_REQUEST` → 等待 `READ_RESPONSE`（5 秒超時）
- 收到後解析黑板歷史，逐條印出
- 超時則放棄同步，直接進入主迴圈

**主迴圈 (Phase 2) — `zmq.Poller` 同時監聽三個 fd:**

| fd | 觸發條件 | 動作 |
|----|----------|------|
| `dealer` | Server 回覆 | 靜默處理 ACK / READ_RESPONSE |
| `sub` | PUB 廣播 | 解析 `STATE_UPDATE`，印出來源與內容（排除自己） |
| `sys.stdin` | 使用者輸入 | 一行一筆 WRITE 送出黑板 |

**self-echo 過濾:**
```python
if eid != instance_id:
    print(f"  [BROADCAST] [{eid} ({model})] {content}")
```

### 4.4 commander.py — Human Commander 實作

與 client.py 架構相同，差異點：

- `role` 固定為 `"human_commander"`
- `model` 固定為 `"human"`
- 同步階段額外印出格式化的歷史紀錄（帶序號）
- 寫入時自動加上 `[COMMANDER]` 前綴，方便 AI 辨別人類指令
- 廣播印出時顯示 `role` 欄位

### 4.5 ZMQ 實作細節

**慢加入者問題 (Slow Joiner):**
- PUB/SUB 在 ZMQ 中有慢加入者問題，訂閱者連線後需要一段時間才能收到訊息
- 在測試中以 `time.sleep(0.3)` 緩解
- 在正式環境中，Server 會持續廣播，Client 總會收到後續訊息

**DEALER 與 ROUTER 的 frame 格式:**
- DEALER → ROUTER：2 frames `[identity, payload]`
- ROUTER → DEALER：2 frames `[identity, payload]`（DEALER recv 時只收到 `[payload]`）
- 實作中以 `frames[-1]` 取 payload，兼容 2 和 3 frame 格式

---

## 5. 測試結果

### 5.1 test_end_to_end.py

```
[PASS] Client A synced: 0 entries
[PASS] Client B synced
[PASS] Client A write ACK received
[PASS] Client B received broadcast: 'hello from A'
[PASS] Client B received second broadcast: 'second message'
[PASS] Final blackboard has 3 entries in order

[PASS] All tests passed.
```

### 5.2 測試覆蓋的場景

| # | 場景 | 結果 |
|---|------|------|
| 1 | Client 啟動 → READ_REQUEST → 同步空黑板 | PASS |
| 2 | Client A WRITE → Server ACK 回覆 | PASS |
| 3 | Client A WRITE → Client B 經 PUB 收到廣播 | PASS |
| 4 | 連續兩次 WRITE → 兩次廣播依序到達 | PASS |
| 5 | Client B 也 WRITE → 最終黑板 3 entries 順序正確 | PASS |

---

## 6. 依賴與工具鏈

| 依賴 | 版本 | 用途 |
|------|------|------|
| Python | >=3.10 | 執行環境 |
| pyzmq | >=26.0 | ZeroMQ Python binding |
| uv | 0.10+ | 專案管理、虛擬環境、執行 |
| hatchling | latest | build backend（pyproject.toml） |

無其他第三方依賴。

---

## 7. 已知限制

| 限制 | 說明 | V2 改善方向 |
|------|------|-------------|
| 記憶體黑板 | Server 重啟後歷史遺失 | 加入 SQLite / JSON file 持久化 |
| 無認證機制 | 任何知道 port 的程序都可連線 | 加入 ZMQ CURVE 加密或 token 驗證 |
| 無訊息篩選 | SUB 收到所有廣播 | 支援 per-instance topic filter |
| 無 TTL / 過期 | 黑板無限增長 | 加入 max_entries 或 TTL 機制 |
| stdin polling | `sys.stdin` 在某些環境下無法 poll | 改用 threading + input() |

---

## 8. 建置與安裝

```bash
cd swarmboard
uv sync                     # 安裝依賴
uv run swarmboard-server    # 啟動 Server
uv run swarmboard-client    # 啟動 Client
uv run swarmboard-commander # 啟動 Commander

# 測試
uv run python tests/test_end_to_end.py
```

---

## 9. 結論

V1 實現了完整的 ZMQ 雙通道架構（ROUTER+PUB），驗證了以下核心能力：

- 多 Instance 並發寫入的序列化
- 即時廣播（PUB/SUB）的低延遲通知
- 啟動同步（READ_REQUEST）的歷史恢復
- instance_id 識別的完整鏈路

程式碼量精簡（809 行），零第三方依賴（僅 pyzmq），架構可直接擴展至生產環境。
