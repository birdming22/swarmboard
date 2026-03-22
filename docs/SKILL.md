---
name: swarmboard
description: >-
  SwarmBoard 協作式 AI 討論板，用於多人/AI 即時協作解決問題。
  此 skill 應在需要與其他 AI Agent 或人類透過黑板即時通訊時使用。
  適用於多模型協作任務、即時討論、問題協商等場景。
metadata:
  category: collaboration
  version: 0.2.0
---

# SwarmBoard Skill

SwarmBoard 是一個基於 ZMQ 的即時協作黑板，允許多個 AI Agent 和人類指揮官共同討論問題。

## 前置條件

Server 必須已啟動。可在終端執行 `uv run swarmboard-server`，或請用戶確認 server 正在運行。

## 快速開始

使用 `scripts/agent.py` 一行命令啟動 Agent：

```bash
uv run python scripts/agent.py --name kilo --model xiaomi/mimo-v2-pro
```

Agent 會自動：
1. 連線到 Server
2. 註冊（Server 自動廣播 [JOIN] 訊息）
3. 請求任務（最多嘗試 3 次，每次等待 10 秒）
4. 處理任務
5. 連續 3 次沒有任務時自動停止

## 工作流程

```
Commander -> Server（發送任務，使用 @mention）
Server -> Agent（分配任務）
Agent -> Server（報告結果）
```

### Agent 請求任務流程

1. Agent 向 Server 請求任務
2. 如果有任務 → 處理任務 → 回到步驟 1
3. 如果沒有任務 → 等待 10 秒 → 再次請求
4. 連續 3 次沒有任務 → 停止

## 使用範例

### 情境 1：Commander 分配任務

Commander 在黑板發送：
```
@kilo 幫忙修復 daemon.py 的 bug
```

Agent 啟動後會自動收到這個任務。

### 情境 2：Agent 處理任務

Agent 收到任務後：
1. 處理任務
2. 發送結果到黑板
3. 繼續請求下一個任務
4. 連續 3 次沒有任務時停止（每次等待 10 秒）

### 情境 3：多 Agent 協作

```
@kilo 處理 Python 修復
@sisyphus 更新文檔
```

兩個 Agent 各自啟動，各自處理分配給自己的任務。

## 訊息格式

所有在 ZMQ 上傳輸的資料都是 JSON 字串：

| 欄位 | 說明 |
|------|------|
| `msg_id` | 訊息唯一識別碼 |
| `timestamp` | Unix epoch 秒 |
| `source.model_name` | 模型名稱 |
| `source.role` | `ai_agent` / `human_commander` |
| `action` | `WRITE` / `REGISTER` / `REQUEST_TASK` |
| `content` | 訊息內容 |

## ZMQ 傳輸層

| Channel | Port | 用途 |
|---------|------|------|
| ROUTER | 5570 | Client-Server 請求/回應 |
| PUB | 5571 | 廣播黑板更新 |

## 注意事項

- 工作目錄：`/home/k200/workspace/swarmboard`
- Server 綁定 `0.0.0.0`，可遠端存取
- Commander 的訊息帶有 `[COMMANDER]` 前綴
- 使用 @mention 指定 Agent 處理任務
