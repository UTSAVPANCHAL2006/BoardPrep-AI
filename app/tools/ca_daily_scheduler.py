"""IST midnight job: fetch today's CA once, then prewarm all 11 voice languages to Redis."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from app.common.logger import get_logger
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
    assess_pipeline: Callable[[], Awaitable[tuple[bool, bool]]],
    schedule_pipeline: Callable[..., Awaitable[bool]],
    *,
    ca_cache,
    startup_catchup: bool = True,
) -> None:
    """Background loop — catch-up on boot, then fires at 12:00 AM IST every day."""
    if not CA_MIDNIGHT_PREWARM_ENABLED:
        return

    await asyncio.sleep(8)

    if startup_catchup:
        needs_run, force_fetch = await assess_pipeline()
        if needs_run:
            logger.info(f"Daily CA catch-up on startup (fetch={force_fetch}, 11 languages)")
            started = await schedule_pipeline(force_fetch=force_fetch, force_voice=False)
            if not started:
                logger.info("Daily CA catch-up skipped — pipeline already running")
        else:
            logger.info("Daily CA already complete for today (bundle + 11 languages in Redis)")

    while True:
        wait = seconds_until_next_midnight_ist()
        logger.info(
            f"Midnight CA scheduler sleeping {int(wait // 3600)}h {int((wait % 3600) // 60)}m until IST midnight"
        )
        await asyncio.sleep(wait)
        await asyncio.sleep(3)

        today = ist_now().date()
        if not await ca_cache.try_claim_job(_JOB_NAME, day=today):
            logger.info("Midnight CA job already claimed for today — skipping duplicate worker")
            await asyncio.sleep(60)
            continue

        logger.info(f"Midnight CA job starting for {today.isoformat()} (IST)")
        started = await schedule_pipeline(force_fetch=True, force_voice=False, source="midnight")
        if started:
            logger.info("Midnight CA job scheduled: fresh fetch + 11-language Redis prewarm")
        else:
            logger.info("Midnight CA job skipped — pipeline already running")
        await asyncio.sleep(60)
