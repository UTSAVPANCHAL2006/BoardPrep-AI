"""IST midnight job: fetch today's CA once, then prewarm all 11 voice languages to Redis."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.common.logger import get_logger
from app.config.ca_languages import CA_VOICE_LANGUAGES
from app.config.config import CA_MIDNIGHT_PREWARM_ENABLED

logger = get_logger(__name__)
_IST = ZoneInfo("Asia/Kolkata")
_JOB_NAME = "midnight_ca"


def ist_now() -> datetime:
    return datetime.now(_IST)


def seconds_until_next_midnight_ist() -> float:
    now = ist_now()
    next_midnight = datetime.combine(now.date() + timedelta(days=1), time(0, 0, 0), tzinfo=_IST)
    return max(1.0, (next_midnight - now).total_seconds())


async def start_midnight_ca_scheduler(
    run_pipeline,
    *,
    ca_cache,
    startup_catchup: bool = True,
) -> None:
    """Background loop — fires at 12:00 AM IST every day."""
    if not CA_MIDNIGHT_PREWARM_ENABLED:
        logger.info("Midnight CA scheduler disabled (CA_MIDNIGHT_PREWARM_ENABLED=false)")
        return

    await asyncio.sleep(8)

    if startup_catchup:
        today = ist_now().date()
        cached = await ca_cache.get_bundle(day=today)
        ready_hi = 0
        if cached:
            ready_hi = await ca_cache.count_ready_audio(len(cached), language="hi", day=today)
        if not cached or ready_hi < len(cached):
            logger.info("Midnight CA catch-up on startup (today's bundle/voices incomplete)")
            try:
                await run_pipeline()
            except Exception as e:
                logger.error(f"Midnight CA catch-up failed: {e}")

    while True:
        wait = seconds_until_next_midnight_ist()
        logger.info(f"Midnight CA scheduler sleeping {int(wait // 3600)}h {int((wait % 3600) // 60)}m until IST midnight")
        await asyncio.sleep(wait)
        await asyncio.sleep(3)

        today = ist_now().date()
        if not await ca_cache.try_claim_job(_JOB_NAME, day=today):
            logger.info("Midnight CA job already claimed for today — skipping duplicate worker")
            await asyncio.sleep(60)
            continue

        logger.info(f"Midnight CA job starting for {today.isoformat()} (IST)")
        try:
            await run_pipeline()
            logger.info("Midnight CA job completed: fetch + 11-language Redis prewarm")
        except Exception as e:
            logger.error(f"Midnight CA job failed: {e}")
        await asyncio.sleep(60)
