# Vercel 部署診斷

## 如果看到 404

1. 到 Vercel Dashboard → 你的專案 → Deployments
2. 看最新一次部署的狀態：
   - 綠色勾勾 = 部署成功 → 看下方的 URL
   - 紅色叉叉 = 部署失敗 → 點進去看錯誤
3. 點部署旁邊的連結（畫面上會有一個 URL），在瀏覽器打開

## 可能的 URL 格式

- https://swarmboard.vercel.app/
- https://swarmboard-xxx.vercel.app/（xxx 是隨機字串）
- https://swarmboard-git-main-birdming22.vercel.app/

## 確認 Root Directory

Settings → General → Root Directory 應該顯示 `web`

如果沒有：Edit → 輸入 `web` → Save → 回 Deployments Redeploy

## 確認環境變數

Settings → Environment Variables 應該有：
- NEXT_PUBLIC_SUPABASE_URL
- NEXT_PUBLIC_SUPABASE_ANON_KEY

如果沒有：新增後 → 回 Deployments Redeploy
