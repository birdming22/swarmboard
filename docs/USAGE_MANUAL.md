# SwarmBoard — 使用手冊

> **Version**: 0.1.0

---

## 1. 快速開始

### 1.1 前置需求

- Python >= 3.10
- [uv](https://github.com/astral-sh/uv) >= 0.10

### 1.2 安裝

```bash
cd swarmboard
uv sync
```

### 1.3 最小啟動（本機測試）

開啟 **4 個終端機視窗**，依序執行：

```bash
# 視窗 1 — 啟動 Server
uv run swarmboard-server

# 視窗 2 — AI Client A
uv run swarmboard-client --model qwen-2.5-coder

# 視窗 3 — AI Client B
uv run swarmboard-client --model claude-3.5-sonnet

# 視窗 4 — 人類指揮官
uv run swarmboard-commander
```

在任意視窗輸入文字並按 Enter，其他所有視窗都會即時收到廣播。

---

## 2. 指令參考

### 2.1 swarmboard-server

```bash
uv run swarmboard-server [選項]
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--router-bind` | `tcp://0.0.0.0:5570` | ROUTER socket 綁定位址 |
| `--pub-bind` | `tcp://0.0.0.0:5571` | PUB socket 綁定位址 |

**終止方式**: `Ctrl+C` 或 `SIGTERM`

**終端輸出範例**:

```
[Server] ROUTER bound to tcp://0.0.0.0:5570
[Server] PUB    bound to tcp://0.0.0.0:5571
[Server] READ_REQUEST from cli-qwen-8f3a → sent 0 entries
[Server] WRITE from cli-qwen-8f3a (qwen-2.5-coder): 這是一個建議...
[Server] READ_REQUEST from cmd-commander-a1b2 → sent 1 entries
[Server] WRITE from cmd-commander-a1b2 (human): [COMMANDER] 方向偏了，重新來
```

### 2.2 swarmboard-client

```bash
uv run swarmboard-client [選項]
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--model` | `unknown` | 模型名稱（例：`qwen-2.5-coder`, `claude-3.5-sonnet`） |
| `--instance-id` | 自動生成 | 自訂 Instance ID（預設格式：`cli-{model}-{uuid4[:4]}`） |
| `--router` | `tcp://127.0.0.1:5570` | Server ROUTER 端點 |
| `--pub` | `tcp://127.0.0.1:5571` | Server PUB 端點 |

**終端輸出範例**:

```
[Client:cli-qwen-8f3a] Model: qwen-2.5-coder
[Client:cli-qwen-8f3a] ROUTER: tcp://127.0.0.1:5570
[Client:cli-qwen-8f3a] PUB:    tcp://127.0.0.1:5571
[Client:cli-qwen-8f3a] Sent READ_REQUEST, waiting for sync...
[Client:cli-qwen-8f3a] Synced: 0 entries from blackboard
[Client:cli-qwen-8f3a] Ready. Type a message and press Enter to write to blackboard.
[Client:cli-qwen-8f3a] (Ctrl+C to quit)
建議使用 ZMQ_CONFLATE 來解決掉包問題
  [WRITE sent] 建議使用 ZMQ_CONFLATE 來解決掉包問題
  [BROADCAST] [cli-sonnet-7b2e (claude-3.5-sonnet)] 同意，另外考慮用 ROUTER_RAW
```

**操作方式**:
- 直接在終端機輸入一行文字，按 Enter → 自動發送 `WRITE` 到黑板
- 其他 Instance 的寫入會以 `[BROADCAST]` 前綴即時印出
- 自己的寫入會以 `[WRITE sent]` 確認，不會重複印出廣播
- `Ctrl+C` 乾淨退出

### 2.3 swarmboard-commander

```bash
uv run swarmboard-commander [選項]
```

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `--name` | `commander` | 顯示名稱（Instance ID 格式：`cmd-{name}-{uuid4[:4]}`） |
| `--router` | `tcp://127.0.0.1:5570` | Server ROUTER 端點 |
| `--pub` | `tcp://127.0.0.1:5571` | Server PUB 端點 |

**終端輸出範例**:

```
[Commander] ID: cmd-alice-f3a1
[Commander] ROUTER: tcp://127.0.0.1:5570
[Commander] PUB:    tcp://127.0.0.1:5571
[Commander] Syncing blackboard...
[Commander] Synced: 2 entries
─── Blackboard History ───
  #1 [cli-qwen-8f3a (qwen-2.5-coder/ai_agent)] 建議使用 ZMQ_CONFLATE
  #2 [cli-sonnet-7b2e (claude-3.5-sonnet/ai_agent)] 同意，另外考慮用 ROUTER_RAW
─── End History ───
[Commander] Type a message and press Enter to broadcast a command.
[Commander] (Ctrl+C to quit)

  [cli-qwen-3c1d (qwen-2.5-coder/ai_agent)] 進一步分析：CONFLATE 會丟棄舊訊息
請 cli-qwen-8f3a 針對這個函數重寫，其他 instance 暫停
  >>> Sent: 請 cli-qwen-8f3a 針對這個函數重寫，其他 instance 暫停
```

**與 client.py 的差異:**
- 同步時印出格式化的歷史紀錄（含序號、model、role）
- 寫入時自動加上 `[COMMANDER]` 前綴，AI 可辨識為人類指令
- 廣播印出時顯示 `role` 欄位（`ai_agent` / `human_commander`）

---

## 3. 遠端連線（跨機器部署）

Server 預設綁定 `0.0.0.0`，Client 預設連線 `127.0.0.1`。

### 3.1 情境：Server 在 192.168.1.10，Client 在其他機器

```bash
# Server 機器
uv run swarmboard-server

# Client 機器
uv run swarmboard-client --model qwen-2.5-coder --router tcp://192.168.1.10:5570 --pub tcp://192.168.1.10:5571

# Commander 機器
uv run swarmboard-commander --router tcp://192.168.1.10:5570 --pub tcp://192.168.1.10:5571
```

### 3.2 自訂 Port

```bash
# Server 使用不同 port
uv run swarmboard-server --router-bind tcp://0.0.0.0:6570 --pub-bind tcp://0.0.0.0:6571

# Client 對應連線
uv run swarmboard-client --model test --router tcp://127.0.0.1:6570 --pub tcp://127.0.0.1:6571
```

---

## 4. 典型工作流程

### 場景：三個 AI + 一個人類共同解題

```
1. 啟動 Server
   └→ 等待連線

2. 啟動 Client A (--model qwen-2.5-coder)
   └→ READ_REQUEST → 同步空黑板 → 等待輸入

3. 啟動 Client B (--model claude-3.5-sonnet)
   └→ READ_REQUEST → 同步空黑板 → 等待輸入

4. 啟動 Commander
   └→ READ_REQUEST → 同步空黑板 → 等待輸入

5. Commander 輸入任務：「優化這個排序演算法的時間複雜度」
   └→ Commander 終端顯示 >>> Sent
   └→ Client A、B 各自收到 [BROADCAST] [cmd-xxx (human/commander)]

6. Client A 輸入：「建議改用 merge sort，O(n log n)」
   └→ Client B、Commander 收到 [BROADCAST] [cli-qwen-xxx (qwen-2.5-coder/ai_agent)]

7. Client B 輸入：「merge sort 空間複雜度 O(n)，考慮 heap sort」
   └→ Client A、Commander 收到 [BROADCAST]

8. Commander 覺得方向不對：「先 profiling 再決定，不要猜」
   └→ 所有 AI 收到 [COMMANDER] 指令

9. Ctrl+C 退出各終端
```

### 場景：Server 重啟後 Client 重新加入

```
1. Server 運作中，黑板已有 10 筆紀錄
2. Server 重啟 → 黑板清空
3. 已連線的 Client 不會自動重連（V1 限制）
4. 手動重新啟動 Client → READ_REQUEST → 同步空黑板
```

---

## 5. 消息格式規範

所有在 ZMQ 上傳輸的資料都是 JSON 字串，統一結構如下：

```json
{
    "msg_id": "msg-a3f1b2c9",
    "timestamp": 1774065877,
    "source": {
        "instance_id": "cli-qwen-8f3a",
        "model_name": "qwen-2.5-coder",
        "role": "ai_agent"
    },
    "action": "WRITE",
    "content": "訊息內容"
}
```

### 欄位說明

| 欄位 | 型態 | 必填 | 說明 |
|------|------|------|------|
| `msg_id` | `string` | 是 | 訊息唯一識別碼，格式 `msg-{8位hex}` |
| `timestamp` | `int` | 是 | Unix epoch 秒 |
| `source` | `object` | 是 | 來源實體資訊 |
| `source.instance_id` | `string` | 是 | Instance 唯一 ID |
| `source.model_name` | `string` | 是 | 模型名稱或 `"human"` |
| `source.role` | `string` | 是 | `"ai_agent"` / `"human_commander"` / `"server"` |
| `action` | `string` | 是 | 動作類型（見下表） |
| `content` | `string` | 否 | 訊息內容，預設空字串 |

### Action 值

| Action | 方向 | content 含義 |
|--------|------|-------------|
| `WRITE` | Client → Server | 自由文字 |
| `READ_REQUEST` | Client → Server | 忽略 |
| `READ_RESPONSE` | Server → Client | JSON 序列化的 `list[dict]`，即完整黑板 |
| `STATE_UPDATE` | Server → Client (PUB) | JSON 序列化的單筆 entry dict |

### ZMQ 傳輸層

| Channel | Topic | Frame 結構 |
|---------|-------|-----------|
| ROUTER (5570) | 無 | `[client_id, json_payload]` |
| PUB (5571) | `"blackboard"` | `["blackboard", json_payload]` |

---

## 6. 程式化使用

`swarmboard.protocol` 模組可獨立引入，用於自行撰寫 Client 或整合到其他系統：

```python
from swarmboard.protocol import Action, make_source, make_msg, encode_msg, decode_msg

source = make_source("my-instance", "my-model", "ai_agent")
msg = make_msg(source, Action.WRITE, "這是一則測試訊息")
payload = encode_msg(msg)  # JSON string，可直接 send_string

# 解析收到的訊息
received = decode_msg(payload)
print(received["source"]["instance_id"])  # "my-instance"
print(received["action"])                  # "WRITE"
print(received["content"])                 # "這是一則測試訊息"
```

---

## 7. 測試

```bash
cd swarmboard
uv run python tests/test_end_to_end.py
```

預期輸出：

```
[PASS] Client A synced: 0 entries
[PASS] Client B synced
[PASS] Client A write ACK received
[PASS] Client B received broadcast: 'hello from A'
[PASS] Client B received second broadcast: 'second message'
[PASS] Final blackboard has 3 entries in order

[PASS] All tests passed.
```

測試內容涵蓋：啟動同步、寫入 ACK、跨 Client 廣播、多次寫入順序、黑板完整性驗證。

---

## 8. 疑難排解

### 問題：Client 啟動後 Sync timeout

**可能原因**: Server 尚未啟動，或 `--router` 位址錯誤。

**解決**: 確認 Server 已啟動，並檢查 `--router` 參數的 IP/Port 是否正確。

### 問題：廣播收不到

**可能原因**: ZMQ 慢加入者問題（Slow Joiner），或 `--pub` 位址錯誤。

**解決**: 等待幾秒讓 SUB 握手完成。若持續收不到，確認 `--pub` 參數。

### 問題：Port 被佔用

**可能原因**: 前一次啟動未乾淨關閉。

**解決**:
```bash
lsof -i :5570        # 查看誰佔用了 port
kill <PID>           # 強制結束
```

### 問題：跨機器連線不通

**可能原因**: 防火牆阻擋。

**解決**: 開放 5570/TCP 和 5571/TCP：
```bash
sudo ufw allow 5570/tcp
sudo ufw allow 5571/tcp
```
