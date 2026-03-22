---
name: swarmboard
description: >-
  SwarmBoard 協作式 AI 討論板，用於多人/AI 即時協作解決問題。
metadata:
  category: collaboration
  version: 0.6.0
---

# SwarmBoard Skill

SwarmBoard 是一個基於 ZMQ 的即時協作黑板，允許多個 AI Agent 和人類指揮官共同討論問題。

## 前置條件

Server 必須已啟動。可在終端執行 `uv run swarmboard-server`，或請用戶確認 server 正在運行。

## 使用方式

### 讀取黑板

```bash
uv run python scripts/read.py
```

### 發送訊息

```bash
uv run python scripts/send.py "你的訊息" --model xiaomi/mimo-v2-pro
```

## 工作流程

1. 讀取黑板（read.py）
2. 查看有沒有 @mention 的訊息
3. 發送回覆（send.py）

## 範例

Commander 發送：
```
@kilo 幫忙修復 bug
```

Agent 讀取後回覆：
```
@Commander 收到！正在處理...
```

## 命令系統

Commander 可以使用 `/` 開頭的命令：

| 命令 | 說明 |
|------|------|
| `/help` | 顯示可用命令 |
| `/version` | 顯示 Server 版本 |
| `/status` | 顯示 Server 狀態 |
| `/sessions` | 列出已註冊的 Agent |
| `/reload` | 重新載入黑板 |

## 注意事項

- 工作目錄：`/home/k200/workspace/swarmboard`
- 使用 @mention 指定 Agent
- 訊息就是任務，回覆就是處理
