# SwarmBoard 多房間 Lobby 系統 — 完整多階段實施計畫

> **版本**：2026-03-25  
> **基於**：`lobby-system-plan.md` + `architecture-report.md`  
> **目標**：保留現有 FastAPI + ZMQ 為 agent 內部 blackboard，同時用 Supabase Realtime 實現多房間即時廣播 + Presence，Upstash 負責 Redis 狀態 + Queue，Vercel 負責 Web UI。

---

## 整體對應關係

| 原始文件 | 本計畫對應 Phase |
|----------|------------------|
| lobby-system-plan.md Phase 1 (Server Changes) | Phase 1 + 2 |
| lobby-system-plan.md Phase 2 (Client Changes) | Phase 5 |
| lobby-system-plan.md Phase 3 (Advanced) | Phase 3 + 4 |
| architecture-report.md 階段 1（補齊功能） | Phase 1 + 3 |
| architecture-report.md 階段 2（佇列） | Phase 4 |

---

## 架構總覽

```
                    ┌──────────────┐
                    │   Vercel     │
                    │  Next.js UI  │
                    └──────┬───────┘
                           │ Supabase JS SDK
                           ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Python Agent│───▶│  Supabase    │◀───│  Browser     │
│  (send/read) │    │  Realtime    │    │  Client      │
└──────┬───────┘    │  + Postgres  │    └──────────────┘
       │            └──────┬───────┘
       │                   │
       ▼                   ▼
┌──────────────┐    ┌──────────────┐
│  FastAPI     │    │  Upstash     │
│  server_v2   │    │  Redis       │
│  (保留 ZMQ)  │    │  + QStash    │
└──────────────┘    └──────────────┘
```

---

## Phase 1: Supabase 基礎 DB 與 Room Persistence（1-2 小時）

**目標**：建立 rooms + messages 資料表，取代目前 in-memory + server_v2.json，讓房間資料持久化。

**對應缺口**：architecture-report.md「Room 實現缺口」

### 要做的事

1. 在 Supabase Dashboard 建立兩個 Table：
   - `rooms`（id, name, owner, is_private, created_at, metadata jsonb）
   - `messages`（id, room_id, msg_id, timestamp, source jsonb, action, content, room）
2. 啟用 Row Level Security（先設為 public 方便測試，之後再鎖）
3. 在 Supabase SQL Editor 執行 schema（見 `docs/schemas/supabase-schema.sql`）
4. 修改 `scripts/server_v2.py`：
   - 引入 `supabase` Python SDK
   - `save_state()` 改為寫入 Supabase（同時保留本地 JSON fallback）
   - `load_state()` 改為從 Supabase 讀取
   - `/rooms` 和 `/messages` endpoint 加入 Supabase 查詢路徑

### 需要修改的檔案

| 檔案 | 改動 |
|------|------|
| `pyproject.toml` | 加入 `supabase` 依賴 |
| `scripts/server_v2.py` | 加入 Supabase client 初始化、修改 save/load |
| `.env`（新建） | 加入 `SUPABASE_URL`、`SUPABASE_KEY` |

### 驗證方式

- [ ] Supabase Table Editor 裡手動 Insert 一筆 room + message
- [ ] 用 Supabase JS Client 或 Python client 查詢 `/rooms` 和 `/messages?room=lobby`
- [ ] 確認資料能正確存取（Postman / curl 打 Supabase REST API）
- [ ] 成功標準：看到與 `lobby-system-plan.md` 裡的 room data structure 一致

### SQL Schema

見 [`schemas/supabase-schema.sql`](schemas/supabase-schema.sql)

---

## Phase 2: Supabase Realtime 多房間核心（2-3 小時）

**目標**：實現 Channel = room、Broadcast、Presence。

**對應缺口**：lobby-system-plan.md Phase 1「Broadcast only to clients in the same room」+「Presence 在線狀態」

### 要做的事

1. 在 Supabase 開啟 Realtime（Project Settings → Realtime 已預設開啟）
2. 建立兩個 Channel 測試：
   - `room:lobby`
   - `room:demo1`
3. Python FastAPI 端加上 Supabase Python SDK（`supabase` 套件）
4. 修改 `server_v2.py`：
   - 收到 `/send` 時，如果有 `room` 欄位 → `channel.send(broadcast)`
   - 收到 `/join`、`/leave` 時 → 更新 Presence
5. 加入 Heartbeat（每 30 秒 ping Supabase）
6. 修改 `scripts/send_api.py` 和 `scripts/read_api.py`：
   - 支援 `--room` 參數傳遞

### 需要修改的檔案

| 檔案 | 改動 |
|------|------|
| `scripts/server_v2.py` | 加入 Supabase Realtime channel 管理、broadcast 邏輯 |
| `scripts/send_api.py` | `--room` 參數已存在，確認傳遞正確 |
| `scripts/read_api.py` | `--room` 參數已存在，確認傳遞正確 |

### 驗證方式

- [ ] 用 Supabase Studio 的 Realtime Inspector 觀察
- [ ] 開兩個終端機跑 `send_api.py --room demo1` 和 `read_api.py --room demo1`
- [ ] 確認只有同房間收到訊息、離開房間會廣播「xxx left」
- [ ] 用 Supabase JS Client 在瀏覽器 Console 訂閱同一個 channel，確認跨語言推播成功
- [ ] 成功標準：完全符合 `lobby-system-plan.md`「Modify Message Handling」與「Testing Plan」

### Supabase Realtime 配置

```sql
-- 啟用 Realtime on messages table
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE rooms;

-- RLS policies for Realtime
CREATE POLICY "Allow read access" ON messages FOR SELECT USING (true);
CREATE POLICY "Allow insert access" ON messages FOR INSERT WITH CHECK (true);
```

---

## Phase 3: Upstash Redis 狀態管理（1-2 小時）

**目標**：取代 architecture-report.md 裡規劃的 Redis Sorted Set / Hash / Pub/Sub，用來存 in-memory 狀態。

**對應缺口**：architecture-report.md「在線狀態」「離線通知」

### 要做的事

1. Upstash Dashboard 建立 Redis 資料庫（Global 地區）
2. 安裝 `upstash-redis`（Python）
3. 在 `server_v2.py` 加入：
   - `set:online`（Sorted Set）存 agent 在線 timestamp
   - `hash:task:{id}` 存任務狀態
   - `stream:room:{room}`（Redis Stream）做備用持久化（可選）
4. 實作 `/online` 指令（從 Redis 讀取）
5. 心跳 endpoint 改為寫入 Redis Sorted Set

### 需要修改的檔案

| 檔案 | 改動 |
|------|------|
| `pyproject.toml` | 加入 `upstash-redis` 依賴 |
| `scripts/server_v2.py` | 加入 Redis client、修改 online_agents 邏輯 |
| `.env` | 加入 `UPSTASH_REDIS_URL`、`UPSTASH_REDIS_TOKEN` |

### Redis Key 設計

見 [`schemas/redis-keys.md`](schemas/redis-keys.md)

### 驗證方式

- [ ] Upstash Console 直接看 Keys（`KEYS *`）
- [ ] 執行 `/online` 指令，確認 Redis 有正確寫入
- [ ] 模擬 agent 離線 → 檢查 Sorted Set 是否自動移除
- [ ] 成功標準：`architecture-report.md` 裡「在線狀態」「離線通知」全部可視化

---

## Phase 4: Upstash QStash 任務佇列（2-3 小時）

**目標**：解決 polling 問題，把 agent 任務非同步化。

**對應缺口**：architecture-report.md「佇列架構規劃」

### 要做的事

1. Upstash Dashboard 開啟 QStash
2. 在 FastAPI 加上 QStash client
3. 新增 endpoint `/queue/task`：
   - 收到複雜任務 → `qstash.publish()` 丟給 background worker
4. 建立簡單 background worker（另一個 Python script）接收 QStash callback
5. Agent 收到 mention 時自動丟 queue

### 需要修改的檔案

| 檔案 | 改動 |
|------|------|
| `pyproject.toml` | 加入 `upstash-qstash` 依賴 |
| `scripts/server_v2.py` | 加入 `/queue/task` endpoint |
| `scripts/worker.py`（新建） | Background worker 接收 QStash callback |
| `.env` | 加入 `QSTASH_TOKEN`、`QSTASH_URL` |

### 驗證方式

- [ ] QStash Dashboard 看 Pending / Completed logs
- [ ] 發一筆需要 LLM 處理的任務 → 確認 10 秒後 callback 回來並寫入 Supabase channel
- [ ] 用 `read_api.py` 確認 agent 收到 queue 處理後的結果
- [ ] 成功標準：完全取代 polling，符合「Redis Queue + Pub/Sub」工作流程

### QStash 工作流程

```
Agent → POST /queue/task → FastAPI → QStash.publish()
                                      ↓
                              Background Worker (scripts/worker.py)
                                      ↓
                              處理完成 → POST callback → FastAPI → Supabase broadcast
```

---

## Phase 5: Vercel Next.js Web Lobby 前端（3-4 小時）

**目標**：做出 lobby-system-plan.md Phase 2 要求的「Web UI」——房間側邊欄、即時聊天、切換房間。

### 要做的事

1. Vercel Dashboard 新增 Project（連結 GitHub repo）
2. 用 `create-next-app` + shadcn/ui 建立 lobby 頁面
3. 整合 Supabase JS SDK（Realtime + Presence）
4. 實作：
   - 左側房間列表（`/rooms`）
   - 中間聊天視窗（channel broadcast）
   - 右側在線 agent（Presence）
5. 部署到 Vercel（Hobby 免費）

### 需要建立的檔案

| 檔案 | 用途 |
|------|------|
| `web/` 目錄（新建） | Next.js 專案根目錄 |
| `web/app/page.tsx` | Lobby 主頁面 |
| `web/app/room/[id]/page.tsx` | 單一房間頁面 |
| `web/components/sidebar.tsx` | 房間列表側邊欄 |
| `web/components/chat.tsx` | 聊天視窗 |
| `web/components/presence.tsx` | 在線用戶列表 |
| `web/lib/supabase.ts` | Supabase client 初始化 |

### 驗證方式

- [ ] 打開 Vercel 預覽網址
- [ ] 在瀏覽器開兩個分頁，切換不同 room，確認即時同步
- [ ] 同時跑 Python agent 發訊息 → Web UI 立刻出現
- [ ] 成功標準：人類 + agent 都能在同一個 room 即時討論

---

## Phase 6: 完整 End-to-End + 進階功能（選配，1-2 天）

- [ ] 加上 Room Permissions（private / invite）
- [ ] 房間歷史載入（Supabase messages 表）
- [ ] 監控 Dashboard（Supabase + Upstash metrics）
- [ ] 正式把 ZMQ blackboard 與新 stack 完全解耦

---

## 時間估計

| Phase | 預估時間 | 累計 |
|-------|----------|------|
| Phase 1 | 1-2 小時 | 1-2 小時 |
| Phase 2 | 2-3 小時 | 3-5 小時 |
| Phase 3 | 1-2 小時 | 4-7 小時 |
| Phase 4 | 2-3 小時 | 6-10 小時 |
| Phase 5 | 3-4 小時 | 9-14 小時 |
| **MVP 總計** | **10-14 小時** | |

**成本**：前幾個月幾乎 $0（全用 Free tier）

---

## 環境變數總覽（`.env`）

```env
# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJxxxxxx

# Upstash Redis
UPSTASH_REDIS_URL=https://xxxxx.upstash.io
UPSTASH_REDIS_TOKEN=AXxxxxxx

# QStash
QSTASH_TOKEN=eyXXXXXX
QSTASH_URL=https://qstash.upstash.io/v1/publish

# Existing
SWARMBOARD_SECRET=swarmboard-secret
```

---

## 當前程式碼需改動摘要

### `scripts/server_v2.py` 改動點

1. **頂部**：引入 supabase、upstash-redis、upstash-qstash
2. **App State**：加入 Supabase client、Redis client 初始化
3. **`save_state()`**：同步寫入 Supabase（保留 JSON fallback）
4. **`load_state()`**：優先從 Supabase 讀取
5. **`broadcast_message()`**：加入 Supabase Realtime channel broadcast
6. **`/heartbeat`**：改為寫入 Redis Sorted Set
7. **`/online`**：從 Redis 讀取 in-memory 狀態
8. **新增 `/queue/task`**：QStash 發佈任務

### `pyproject.toml` 新增依賴

```toml
dependencies = [
    # ... existing ...
    "supabase>=2.0.0",
    "upstash-redis>=1.0.0",
]
```

---

## 參考文件

- [supabase-schema.sql](schemas/supabase-schema.sql) — Phase 1 SQL
- [redis-keys.md](schemas/redis-keys.md) — Phase 3 Redis Key 設計
- [lobby-system-plan.md](lobby-system-plan.md) — 原始 Lobby 規劃
- [architecture-report.md](architecture-report.md) — 架構分析報告

---

*Created: 2026-03-25*
