import re
import time

from app.common.logger import get_logger

logger = get_logger(__name__)

_cooldown_until = 0.0


def groq_is_cooling() -> bool:
    return time.monotonic() < _cooldown_until


def groq_cooldown_left() -> float:
    return max(0.0, _cooldown_until - time.monotonic())


def groq_wait_from_error(err: Exception) -> float:
    text = str(err)
    match = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s", text, re.I)
    if match:
        hours = int(match.group(1) or 0)
        mins = int(match.group(2) or 0)
        secs = float(match.group(3) or 0)
        return min(3600.0, hours * 3600 + mins * 60 + secs + 1.0)
    match = re.search(r"try again in ([0-9.]+)s", text, re.I)
    if match:
        return min(3600.0, float(match.group(1)) + 0.5)
    if "tokens per day" in text.lower() or "tpd" in text.lower():
        return 180.0
    return 60.0


def groq_mark_limited(err: Exception | None = None) -> float:
    """Pause Groq calls briefly after 429 so retries do not burn the quota."""
    global _cooldown_until
    text = str(err or "").lower()
    if "payment required" in text or "insufficient" in text:
        seconds = 30.0
    else:
        seconds = min(5.0, groq_wait_from_error(err) if err else 5.0)
    _cooldown_until = time.monotonic() + seconds
    logger.warning(f"Groq cooldown {seconds:.0f}s — using local notes until it lifts")
    return seconds


def groq_error_is_rate_limit(err: Exception) -> bool:
    text = str(err).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text
