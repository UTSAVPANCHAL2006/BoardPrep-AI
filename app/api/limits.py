"""Rate limits for the calls that cost money (an LLM or speech model runs on each): per person and for everyone together,
so one person, or a script using many addresses, cannot run up the AI bill."""

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

WINDOW_SECONDS = 600
PER_PERSON = {"daf": 20, "start": 30, "answer": 150}
FOR_EVERYONE = {"daf": 200, "start": 300, "answer": 1500}
GROUPS = {"/upload-daf": "daf", "/start-interview": "start", "/respond": "answer", "/respond-stream": "answer"}

recentRequests: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def readClientId(request: Request) -> str:
    """Behind Cloudflare (Render) CF-Connecting-IP is set by Cloudflare and cannot be faked. X-Forwarded-For is never
    trusted: its first address is whatever the caller wrote."""
    cloudflare = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare:
        return cloudflare
    return request.client.host if request.client else "unknown"


def isOverLimit(key: tuple[str, str], limit: int) -> bool:
    """True when this key used up its requests in the window; otherwise the request is counted."""
    now = time.monotonic()
    times = recentRequests[key]
    while times and now - times[0] > WINDOW_SECONDS:
        times.popleft()
    if len(times) >= limit:
        return True
    times.append(now)
    return False


async def limitRequests(request: Request, callNext):
    group = GROUPS.get(request.url.path) if request.method == "POST" else None
    if group and (
        isOverLimit((readClientId(request), group), PER_PERSON[group])
        or isOverLimit(("everyone", group), FOR_EVERYONE[group])
    ):
        return JSONResponse({"detail": "Too many requests in a few minutes. Please wait a little and try again."}, 429)
    return await callNext(request)
