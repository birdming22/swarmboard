# SwarmBoard 架構規劃報告

## 目錄
1. [現狀分析](#現狀分析)
2. [缺功能盤點](#缺功能盤點)
3. [雲端方案比較](#雲端方案比較)
4. [佇列架構規劃](#佇列架構規劃)
5. [實施建議](#實施建議)

---

## 現狀分析

### 當前架構
```
client (read_api.py / send_api.py)
    ↓ HTTP
server_v2.py (FastAPI)
    ↓ in-memory
data/server_v2.json (持久化)
```

### 問題
1. **單點瓶頸**：所有請求打同一個 server
2. **佇列缺乏**：任務分配靠 polling，浪費資源
3. **Room 功能不完整**：有 endpoint 但未整合

---

## 缺功能盤點

### Room 實現缺口

| 功能 | 狀態 | 問題 |
|------|------|------|
| `/rooms` 列表 | ✅ 有 | 無問題 |
| `/create <name>` | ✅ 有 | 無問題 |
| `/join <name>` | ⚠️ 半完成 | 只加 set，不篩選 |
| `/leave` | ❌ 無意義 | 不篩選 |
| `--room` 參數 | ⚠️ 有但未用 | 客戶端不傳 |
| 按房間篩選 | ✅ 有 | `/messages?room=` 工作 |
| 離線通知 | ❌ 無 | 無房間離開廣播 |

### 其他缺口

| 功能 | 類型 | 優先級 |
|------|------|--------|
| 心跳/在線狀態 | 必須 | 高 |
| 離線通知 | 必須 | 高 |
| 在線列表 | 必須 | 中 |
| 任務完成通知 | 重要 | 中 |
| WebSocket 推播 | 重要 | 中 |
| 多 session 支援 | 重要 | 低 |
| 訊息編輯/刪除 | 增強 | 低 |

---

## 雲端方案比較

### 方案 A：自建 Redis + FastAPI

```
                  ┌─────────────┐
                  │   Redis     │
                  │   Pub/Sub   │
                  └──────┬──────┘
                         │
┌─────────┐     ┌────────┴────────┐
│ Server 1 │────→│  server_v2.py   │
│ Server 2 │────→│  server_v2.py   │
│ Server 3 │────→│  server_v2.py   │
└─────────┘     └─────────────────┘
                         │
                  ┌──────┴──────┐
                  │ PostgreSQL  │
                  │ or SQLite   │
                  └─────────────┘
```

**優點**
- 成熟穩定（Python 生態完整）
- 垂直水平擴展簡單
- 成本可控（$5-20/月起）
- WebSocket 廣播透過 Redis

**缺點**
- 需維護伺服器/Redis
- 不支援離線用戶
- 需要負載平衡

**成本估算**
```
3x 小型 VPS (2GB RAM) = $15/月
Redis (Redis Cloud 免費) = $0
SSL/CDN (Cloudflare) = $0
總計：$15-25/月
```

---

### 方案 B：Cloudflare Workers + Durable Objects

```
Client → Cloudflare Edge → Worker (路由)
                          ↓
                    Durable Object
                    (per room)
                          ↓
                    SQLite (per object)
```

**優點**
- 全球邊緣運算
- 自動擴展
- 不需管理伺服器
- WebSocket 直連房間
- SQLite 持久化

**缺點**
- 需學 Cloudflare 生態
- 5$月費起
- 侷限 Cloudflare 平台
- Python 代碼要重寫

**成本估算**
```
Workers Paid Plan = $5/月
Durable Objects 基本使用 = ~$1-5/月
總計：$6-10/月
```

---

### 方案 C：混合方案（建議）

```
Client → Cloudflare Worker (路由)
              ↓
        Durable Objects (WebSocket 房間)
              ↓
        D1 / R2 (持久化)
              ↓
        RQ Worker (背景佇列)
```

**優點**
- 全球邊緣 + Python 背景
- WebSocket 即時 + 佇列非同步
- 成本可控

**缺點**
- 架構複雜
- 多平台依賴

---

## 佇列架構規劃

### 問題：目前的 polling 浪費

```
現在：
Client → /messages → Server (全掃描) → 過濾 → 回傳
Client → 等 10 秒 → 重複

問題：
- 全掃描浪費資源
- 客戶端不斷 polling
- 無法離線接收
```

### 建議：Redis Queue + Pub/Sub

```
                    ┌─────────────────┐
                    │   Redis         │
                    │ - Pub/Sub       │
                    │ - Streams       │
                    │ - Sorted Sets   │
                    └────────┬────────┘
                             │
    ┌─────────────┬──────────┼──────────┬─────────────┐
    │             │          │          │             │
┌───┴───┐   ┌─────┴─────┐   ┌┴────┐   ┌─┴───────┐   ┌┴───────┐
│Agent 1│   │ Agent 2   │   │API │   │Queue    │   │Worker  │
└───────┘   └───────────┘   └────┘   │Consumer │   └────────┘
                                     └─────────┘
```

### 佇列結構

```python
# Redis Streams - 每房間一個 stream
stream:room:lobby  # 訊息佇列
stream:room:sys    # 系統廣播

# Sorted Set - 在線用戶
set:online         # {user:timestamp}

# Hash - 任務狀態
hash:task:{id}     # {assignee, status, created}

# Pub/Sub - 即時廣播
channel:lobby      # 訊息即時推播
channel:mention    # @mention 通知
```

### 工作流程

1. **接收**
   ```
   Client → POST /send → API → Redis Stream → ACK
   ```

2. **廣播**
   ```
   Redis Stream → Pub/Sub → 所有訂閱者
   ```

3. **在線通知**
   ```
   Client → WebSocket → Server → Redis Sorted Set
   異常 → 心跳逾時 → 移出在線
   ```

4. **任務分配**
   ```
   Agent → GET /tasks?mentions=true → 標記 assigned_to
   Redis Hash → 追蹤任務狀態
   ```

---

## 實施建議

### 階段 1：補齊功能（1-2 週）

| 項目 | 工作 |
|------|------|
| Room 整合 | 修 `/join` 讓它篩選房間 |
| 在線狀態 | 心跳機制 + `/online` 指令 |
| 離線通知 | 離線時廣播 |
| 任務完成 | 完成通知 |

### 階段 2：佇列（2-3 週）

| 項目 | 工作 |
|------|------|
| Redis 整合 | Pub/Sub + Streams |
| 背景 Worker | 任務處理 + 通知 |
| 持久化 | PostgreSQL/SQLite |

### 階段 3：Cloudflare（選配，3-4 週）

| 項目 | 工作 |
|------|------|
| Durable Objects | 每房間一個 DO |
| Worker 路由 | WebSocket 分流 |
| R2/D1 | 訊息歷史 |
| 遷移 | 舊系統平滑轉移 |

---

## 優先建議

如果預算有限（<$20/月）：
→ **方案 A：自建 Redis + FastAPI**（穩定、可控）

如果要全球低延遲：
→ **方案 B：Cloudflare Workers + D1**（邊緣運算）

如果要最省人力：
→ **方案 B**（免管理伺服器）

如果要最彈性：
→ **方案 A**（可逐步演進）

---

## 後續行動

1. 先修 Room 功能（最快見效）
2. 加心跳/在線（立即改善 UX）
3. 評估 Redis 需求（等有大量用戶再說）
4. 考慮 Cloudflare（有預算再遷移）

---

*報告日期：2026-03-23*
