#!/usr/bin/env python3
"""Wipe CA article + voice briefing keys from Redis (fixes story/audio mismatch).

Usage:
  REDIS_URL='rediss://default:...@....upstash.io:6379' python scripts/clear_ca_redis.py
  REDIS_URL='...' python scripts/clear_ca_redis.py --refresh   # also hit API after deploy
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


async def clear_ca_redis(redis_url: str) -> dict[str, int]:
    import redis.asyncio as redis

    client = redis.from_url(redis_url, decode_responses=True)
    deleted = {"bundles": 0, "explains": 0, "other": 0}
    try:
        await client.ping()
        async for key in client.scan_iter(match="ca_bundle:*"):
            await client.delete(key)
            deleted["bundles"] += 1
        async for key in client.scan_iter(match="ca_explain_v15:*"):
            await client.delete(key)
            deleted["explains"] += 1
        async for key in client.scan_iter(match="ca_*"):
            await client.delete(key)
            deleted["other"] += 1
    finally:
        await client.aclose()
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear BoardPrep daily CA Redis cache")
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", ""),
        help="Redis URL (default: REDIS_URL env)",
    )
    args = parser.parse_args()
    if not args.redis_url:
        print("Set REDIS_URL or pass --redis-url", file=sys.stderr)
        sys.exit(1)

    deleted = asyncio.run(clear_ca_redis(args.redis_url))
    total = sum(deleted.values())
    print(f"Cleared {total} keys: {deleted}")
    print("Restart Railway or wait ~2 min, then reload CA page.")


if __name__ == "__main__":
    main()
