import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.common.logger import get_logger
from app.config.config import CA_BUNDLE_TTL_SECONDS, REDIS_URL
from app.schema.interview import EnrichedArticle

logger = get_logger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_memory_bundles: dict[str, str] = {}
_memory_explains: dict[str, str] = {}
_redis_warned = False


def india_today() -> date:
    return datetime.now(_IST).date()


class CaCache:
    """Daily shared current-affairs bundle in Redis (all sessions reuse same day)."""

    def __init__(self):
        self._url = REDIS_URL
        self._client = None
        self._use_memory = False

    async def connect(self):
        if self._client is not None:
            return
        try:
            import redis.asyncio as redis

            client = redis.from_url(self._url, decode_responses=True)
            await client.ping()
            self._client = client
            self._use_memory = False
            logger.info("CA cache connected to Redis")
        except Exception as e:
            global _redis_warned
            self._use_memory = True
            self._client = None
            if not _redis_warned:
                _redis_warned = True
                logger.warning(f"Redis unavailable, CA cache using memory: {e}")

    def key(self, day: date | None = None) -> str:
        d = day or india_today()
        return f"ca_bundle:{d.isoformat()}"

    async def get_bundle(self, day: date | None = None) -> list[EnrichedArticle] | None:
        await self.connect()
        key = self.key(day)
        if self._use_memory:
            raw = _memory_bundles.get(key)
        else:
            raw = await self._client.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            articles = [EnrichedArticle.model_validate(item) for item in data]
            logger.info(f"CA cache hit: {key} ({len(articles)} articles)")
            return articles
        except Exception as e:
            logger.warning(f"CA cache parse failed: {e}")
            return None

    async def _clear_explains_for_day(self, day: date | None = None) -> int:
        await self.connect()
        key = self.key(day)
        deleted = 0
        if self._use_memory:
            prefix = f"ca_explain_v15:{key}:"
            for k in list(_memory_explains.keys()):
                if k.startswith(prefix):
                    _memory_explains.pop(k, None)
                    deleted += 1
            return deleted
        pattern = f"ca_explain_v15:{key}:*"
        async for k in self._client.scan_iter(match=pattern):
            await self._client.delete(k)
            deleted += 1
        return deleted

    async def set_bundle(self, articles: list[EnrichedArticle], day: date | None = None) -> None:
        await self.connect()
        key = self.key(day)
        cleared = await self._clear_explains_for_day(day)
        payload = json.dumps([a.model_dump() for a in articles])
        if self._use_memory:
            _memory_bundles[key] = payload
            if cleared:
                logger.info(f"CA explain cache cleared before bundle store: {cleared} keys")
            return
        await self._client.setex(key, CA_BUNDLE_TTL_SECONDS, payload)
        logger.info(
            f"CA cache stored: {key} ({len(articles)} articles, TTL {CA_BUNDLE_TTL_SECONDS}s"
            f"{f', cleared {cleared} stale voice keys' if cleared else ''})"
        )

    async def delete_bundle(self, day: date | None = None) -> None:
        await self.connect()
        key = self.key(day)
        if self._use_memory:
            _memory_bundles.pop(key, None)
            cleared = await self._clear_explains_for_day(day)
            logger.info(f"CA cache cleared: {key} (+ {cleared} voice keys)")
            return
        await self._client.delete(key)
        cleared = await self._clear_explains_for_day(day)
        logger.info(f"CA cache cleared: {key} (+ {cleared} voice keys)")

    async def clear_all(self) -> dict[str, int]:
        """Delete every CA bundle + briefing/voice key (fixes story/audio mismatch)."""
        await self.connect()
        deleted = {"bundles": 0, "explains": 0}
        if self._use_memory:
            deleted["bundles"] = len(_memory_bundles)
            deleted["explains"] = len(_memory_explains)
            _memory_bundles.clear()
            _memory_explains.clear()
            logger.info(f"CA memory cache cleared: {deleted}")
            return deleted
        async for k in self._client.scan_iter(match="ca_bundle:*"):
            await self._client.delete(k)
            deleted["bundles"] += 1
        async for k in self._client.scan_iter(match="ca_explain_v15:*"):
            await self._client.delete(k)
            deleted["explains"] += 1
        logger.info(f"CA Redis cache cleared: {deleted}")
        return deleted

    def explain_key(self, article_index: int, language: str = "hi", day: date | None = None) -> str:
        return f"ca_explain_v15:{self.key(day)}:{language}:{article_index}"

    async def get_explain(
        self, article_index: int, day: date | None = None, language: str = "hi"
    ) -> dict | None:
        await self.connect()
        key = self.explain_key(article_index, language, day)
        if self._use_memory:
            raw = _memory_explains.get(key)
        else:
            raw = await self._client.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            logger.info(f"CA explain cache hit: {key}")
            return data
        except Exception as e:
            logger.warning(f"CA explain cache parse failed: {e}")
            return None

    async def set_explain(
        self, article_index: int, payload: dict, day: date | None = None, language: str = "hi"
    ) -> None:
        await self.connect()
        key = self.explain_key(article_index, language, day)
        raw = json.dumps(payload)
        if self._use_memory:
            _memory_explains[key] = raw
            return
        await self._client.setex(key, CA_BUNDLE_TTL_SECONDS, raw)
        logger.info(f"CA explain cached: {key}")

    async def count_ready_audio(
        self, article_count: int, day: date | None = None, language: str = "hi"
    ) -> int:
        ready = 0
        for i in range(article_count):
            data = await self.get_explain(i, day, language)
            if data and data.get("audio_base64"):
                ready += 1
        return ready
