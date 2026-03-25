-- Phase 1: Supabase Schema for SwarmBoard Lobby System
-- 執行方式：在 Supabase SQL Editor 或透過 setup_schema.py 執行

-- Table 1: rooms
CREATE TABLE IF NOT EXISTS rooms (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    owner       TEXT,
    is_private  BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB       DEFAULT '{}'::jsonb
);

-- Table 2: messages
CREATE TABLE IF NOT EXISTS messages (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id     UUID        NOT NULL,
    msg_id      TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source      JSONB       NOT NULL,
    action      TEXT,
    content     TEXT        NOT NULL,
    room        TEXT
);

-- Foreign Key
ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS fk_room;
ALTER TABLE messages
    ADD CONSTRAINT fk_room
    FOREIGN KEY (room_id)
    REFERENCES rooms(id) ON DELETE CASCADE;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_messages_room_id ON messages(room_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_rooms_name ON rooms(name);

-- Seed data: default rooms
INSERT INTO rooms (name, owner, is_private, metadata)
VALUES ('lobby', 'system', false, '{"max_agents": 50, "topic": "main_lobby"}')
ON CONFLICT DO NOTHING;

INSERT INTO rooms (name, owner, is_private, metadata)
VALUES ('demo1', 'system', false, '{"max_agents": 10, "topic": "demo_room"}')
ON CONFLICT DO NOTHING;
