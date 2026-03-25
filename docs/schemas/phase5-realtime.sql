-- Phase 5: Enable Realtime + RLS for Web UI
-- 在 Supabase SQL Editor 執行

-- Enable Realtime on tables
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE rooms;

-- Disable RLS for testing (先開放，之後再加 policy)
ALTER TABLE messages DISABLE ROW LEVEL SECURITY;
ALTER TABLE rooms DISABLE ROW LEVEL SECURITY;
