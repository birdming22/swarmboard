#!/usr/bin/env python3
"""Phase 0 — Verify Upstash Redis connection."""

from upstash_redis import Redis
import os
from dotenv import load_dotenv

load_dotenv()

redis = Redis.from_env()

redis.set("swarmboard_test_key", "Phase 0 成功！")
value = redis.get("swarmboard_test_key")
print("Upstash Redis 連線成功！測試值:", value)

# Cleanup
redis.delete("swarmboard_test_key")
