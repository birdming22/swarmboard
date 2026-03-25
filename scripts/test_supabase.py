#!/usr/bin/env python3
"""Phase 0 — Verify Supabase connection."""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in .env")
    exit(1)

supabase = create_client(url, key)

# Test: try a basic REST call (Supabase exposes /rest/v1/)
# We can't query pg_tables via PostgREST, so just verify auth + connectivity
try:
    # Try to list tables by hitting the REST endpoint directly
    import urllib.request

    req = urllib.request.Request(
        f"{url}/rest/v1/",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Supabase 連線成功！REST API 回傳 status: {resp.status}")
        print(f"Project URL: {url}")
except Exception as e:
    print(f"Supabase 連線測試: {e}")
    # Even a 404/empty response means connection works
    if "404" in str(e) or "400" in str(e):
        print("(404/400 is OK — means Supabase is reachable, just no root endpoint)")
