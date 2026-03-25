#!/usr/bin/env python3
"""
Phase 1 — 建立 Supabase tables（rooms + messages）。

用法：
    uv run python scripts/setup_schema.py

從 .env 讀取 SUPABASE_DB_PASSWORD，透過 Session Pooler（IPv4 相容）連線。
"""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

SCHEMA_SQL = Path(__file__).parent.parent / "docs" / "schemas" / "supabase-schema.sql"

# Session Pooler — 請從 Dashboard → Settings → Database → Connection string 複製正確的 host
DB_HOST = os.getenv("SUPABASE_POOLER_HOST", "aws-0-ap-northeast-1.pooler.supabase.com")
DB_PORT = int(os.getenv("SUPABASE_POOLER_PORT", "5432"))
DB_NAME = "postgres"
DB_USER = "postgres.tawuggyrmfivosyhstiu"
DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "")


def main():
    if not SCHEMA_SQL.exists():
        print(f"ERROR: Schema file not found: {SCHEMA_SQL}")
        sys.exit(1)

    if not DB_PASSWORD:
        print("ERROR: SUPABASE_DB_PASSWORD not set in .env")
        print("Add this line to your .env file:")
        print('  SUPABASE_DB_PASSWORD="your-password-here"')
        sys.exit(1)

    print(f"Connecting to {DB_HOST}:{DB_PORT}/{DB_NAME} as {DB_USER}...")

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            sslmode="require",
        )
        conn.autocommit = False
        cur = conn.cursor()

        sql = SCHEMA_SQL.read_text()
        print("Executing schema SQL...")
        cur.execute(sql)
        conn.commit()

        # Verify
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"\nPublic tables: {tables}")

        cur.execute("SELECT name FROM rooms ORDER BY name")
        rooms = cur.fetchall()
        print(f"Rooms: {[r[0] for r in rooms]}")

        cur.close()
        conn.close()
        print("\nPhase 1 schema 建立完成！")

    except psycopg2.OperationalError as e:
        print(f"Connection failed: {e}")
        print(f"\nDebug info:")
        print(f"  Host: {DB_HOST}")
        print(f"  Port: {DB_PORT}")
        print(f"  User: {DB_USER}")
        print(f"  Password set: {'yes' if DB_PASSWORD else 'no'}")
        print(f"\n可能原因:")
        print(
            f"  1. SUPABASE_POOLER_HOST 不正確 → 從 Dashboard 複製 Session pooler host"
        )
        print(f"  2. 密碼錯誤 → 確認 SUPABASE_DB_PASSWORD")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
