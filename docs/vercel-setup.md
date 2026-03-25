# Vercel 部署設定指南

## 1. Vercel Dashboard 設定

到 https://vercel.com/dashboard → 選 swarmboard 專案 → Settings

### Environment Variables（Settings → Environment Variables）

新增以下兩筆：

```
NEXT_PUBLIC_SUPABASE_URL=https://tawuggyrmfivosyhstiu.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRhd3VnZ3lybWZpdm9zeWhzdGl1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQzOTAwNzcsImV4cCI6MjA4OTk2NjA3N30.GUKkPC0FQr3LaePAhxE_DhQpZP4XjmFGQ_OePfBYh5Q
```

### Root Directory

設為 `web`（因為 Next.js 專案在 web/ 子目錄）

### Framework Preset

Next.js（Vercel 會自動偵測）

## 2. Redeploy

設定完成後，點 Deployments → 最新一次 → Redeploy

## 3. 本地測試

```bash
cd web
npm run dev
# 開啟 http://localhost:3000
```
