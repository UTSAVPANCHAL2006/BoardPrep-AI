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
_memory_jobs: set[str] = set()
_memory_pipeline_done: set[str] = set()
_redis_warned = False
_redis_full_logged = False


def is_redis_memory_error(err: Exception) -> bool:
    msg = f"{type(err).__name__}: {err}".lower()
    return any(
        token in msg
        for token in (
            "oom",
            "maxmemory",
            "memory limit",
            "out of memory",
            "cannot allocate",
            "command not allowed when used memory",
            "read only",
            "readonly",
            "quota exceeded",
            "capacity quota",
            "db capacity",
        )
    )


def india_today() -> date:
    return datetime.now(_IST).date()


class CaCache:
    """Daily shared current-affairs bundle in Redis (all sessions reuse same day)."""

    def __init__(self):
        self._url = REDIS_URL
        self._client = None
        self._use_memory = False
        self._writes_blocked = False
        self._active_bundle_day: date | None = None

    def active_bundle_day(self) -> date:
        return self._active_bundle_day or india_today()

    def _parse_bundle_day(self, key: str) -> date | None:
        prefix = "ca_bundle:"
        if not key.startswith(prefix):
            return None
        try:
            return date.fromisoformat(key[len(prefix) :])
        except ValueError:
            return None

    async def _load_bundle_raw(self, key: str) -> list[EnrichedArticle] | None:
        if self._use_memory:
            raw = _memory_bundles.get(key)
        else:
            raw = await self._client.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            articles = [EnrichedArticle.model_validate(item) for item in data]
            bundle_day = self._parse_bundle_day(key)
            if bundle_day:
                self._active_bundle_day = bundle_day
            logger.info(f"CA cache hit: {key} ({len(articles)} articles)")
            return articles
        except Exception as e:
            logger.warning(f"CA cache parse failed for {key}: {e}")
            return None

    async def _find_latest_bundle_key(self) -> str | None:
        if self._use_memory:
            keys = [k for k in _memory_bundles if k.startswith("ca_bundle:")]
        else:
            keys = [k async for k in self._client.scan_iter(match="ca_bundle:*")]
        best_key: str | None = None
        best_day: date | None = None
        for key in keys:
            bundle_day = self._parse_bundle_day(key)
            if bundle_day and (best_day is None or bundle_day > best_day):
                best_day = bundle_day
                best_key = key
        return best_key

    def writes_enabled(self) -> bool:
        return not self._writes_blocked and not self._use_memory

    def is_storage_full(self) -> bool:
        return self._writes_blocked

    def _block_writes(self, err: Exception, op: str) -> None:
        global _redis_full_logged
        self._writes_blocked = True
        if not _redis_full_logged:
            _redis_full_logged = True
            logger.error(
                f"Redis storage full — CA cache writes stopped for this process ({op}): {err}"
            )

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
        """Today's bundle first, then most recent ca_bundle:* already in Redis (Upstash demo cache)."""
        await self.connect()
        target_day = day or india_today()
        articles = await self._load_bundle_raw(self.key(target_day))
        if articles:
            return articles
        if day is not None:
            return None
        latest_key = await self._find_latest_bundle_key()
        if not latest_key or latest_key == self.key(target_day):
            return None
        articles = await self._load_bundle_raw(latest_key)
        if articles:
            bundle_day = self._parse_bundle_day(latest_key)
            logger.info(
                f"CA reusing Redis bundle from {bundle_day} (today={target_day}) — voice keys preserved"
            )
        return articles

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

    async def set_bundle(self, articles: list[EnrichedArticle], day: date | None = None) -> bool:
        await self.connect()
        key = self.key(day)
        cleared = await self._clear_explains_for_day(day)
        payload = json.dumps([a.model_dump() for a in articles])
        if self._use_memory:
            _memory_bundles[key] = payload
            if cleared:
                logger.info(f"CA explain cache cleared before bundle store: {cleared} keys")
            return True
        if self._writes_blocked:
            return False
        try:
            await self._client.setex(key, CA_BUNDLE_TTL_SECONDS, payload)
            logger.info(
                f"CA cache stored: {key} ({len(articles)} articles, TTL {CA_BUNDLE_TTL_SECONDS}s"
                f"{f', cleared {cleared} stale voice keys' if cleared else ''})"
            )
            return True
        except Exception as e:
            if is_redis_memory_error(e):
                self._block_writes(e, "set_bundle")
            else:
                logger.warning(f"CA bundle cache write failed: {e}")
            return False

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
        global _redis_full_logged
        await self.connect()
        deleted = {"bundles": 0, "explains": 0}
        self._writes_blocked = False
        _redis_full_logged = False
        if self._use_memory:
            deleted["bundles"] = len(_memory_bundles)
            deleted["explains"] = len(_memory_explains)
            _memory_bundles.clear()
            _memory_explains.clear()
            _memory_pipeline_done.clear()
            logger.info(f"CA memory cache cleared: {deleted}")
            return deleted
        async for k in self._client.scan_iter(match="ca_bundle:*"):
            await self._client.delete(k)
            deleted["bundles"] += 1
        async for k in self._client.scan_iter(match="ca_explain_v15:*"):
            await self._client.delete(k)
            deleted["explains"] += 1
        async for k in self._client.scan_iter(match="ca_job:daily_pipeline_done:*"):
            await self._client.delete(k)
        logger.info(f"CA Redis cache cleared: {deleted}")
        return deleted

    async def try_claim_job(self, name: str, day: date | None = None) -> bool:
        """Once-per-day lock so only one worker runs the midnight CA pipeline."""
        await self.connect()
        d = day or india_today()
        key = f"ca_job:{name}:{d.isoformat()}"
        if self._use_memory:
            if key in _memory_jobs:
                return False
            _memory_jobs.add(key)
            return True
        claimed = await self._client.set(key, "1", nx=True, ex=172800)
        return bool(claimed)

    def pipeline_done_key(self, day: date | None = None) -> str:
        d = day or india_today()
        return f"ca_job:daily_pipeline_done:{d.isoformat()}"

    async def is_daily_pipeline_done(self, day: date | None = None) -> bool:
        """True when today's full 11-language prewarm already finished successfully."""
        await self.connect()
        key = self.pipeline_done_key(day)
        if self._use_memory:
            return key in _memory_pipeline_done
        return bool(await self._client.get(key))

    async def mark_daily_pipeline_done(self, day: date | None = None) -> bool:
        await self.connect()
        key = self.pipeline_done_key(day)
        if self._use_memory:
            _memory_pipeline_done.add(key)
            return True
        if self._writes_blocked:
            return False
        try:
            await self._client.setex(key, 172800, "1")
            logger.info(f"Daily CA pipeline marked done: {key}")
            return True
        except Exception as e:
            if is_redis_memory_error(e):
                self._block_writes(e, "mark_daily_pipeline_done")
            else:
                logger.warning(f"Daily CA pipeline done flag write failed: {e}")
            return False

    async def clear_daily_pipeline_done(self, day: date | None = None) -> None:
        await self.connect()
        key = self.pipeline_done_key(day)
        if self._use_memory:
            _memory_pipeline_done.discard(key)
            return
        await self._client.delete(key)

    def explain_key(self, article_index: int, language: str = "hi", day: date | None = None) -> str:
        return f"ca_explain_v15:{self.key(day)}:{language}:{article_index}"

    async def get_explain(
        self, article_index: int, day: date | None = None, language: str = "hi", *, quiet: bool = False
    ) -> dict | None:
        await self.connect()
        bundle_day = day or self._active_bundle_day or india_today()

        def _parse(raw: str | None, key: str) -> dict | None:
            if not raw:
                return None
            try:
                data = json.loads(raw)
                if not quiet:
                    logger.info(f"CA explain cache hit: {key}")
                return data
            except Exception as e:
                logger.warning(f"CA explain cache parse failed for {key}: {e}")
                return None

        keys_to_try = [
            self.explain_key(article_index, language, bundle_day),
            self.explain_key(article_index, language, india_today()),
            f"{language}:{article_index}",
        ]
        if self._active_bundle_day and self._active_bundle_day != bundle_day:
            keys_to_try.insert(1, self.explain_key(article_index, language, self._active_bundle_day))

        seen: set[str] = set()
        for key in keys_to_try:
            if key in seen:
                continue
            seen.add(key)
            if self._use_memory:
                raw = _memory_explains.get(key)
            else:
                raw = await self._client.get(key)
            if not raw:
                continue
            if not raw.lstrip().startswith("{"):
                if not quiet:
                    logger.info(f"CA explain legacy audio hit: {key}")
                return {"audio_base64": raw, "briefing_voice": "", "article_title": ""}
            hit = _parse(raw, key)
            if hit and hit.get("audio_base64"):
                return hit

        if not self._use_memory:
            pattern = f"ca_explain_v15:ca_bundle:*:{language}:{article_index}"
            async for key in self._client.scan_iter(match=pattern):
                hit = _parse(await self._client.get(key), key)
                if hit and hit.get("audio_base64"):
                    return hit

        return None

    async def set_explain(
        self, article_index: int, payload: dict, day: date | None = None, language: str = "hi"
    ) -> bool:
        await self.connect()
        key = self.explain_key(article_index, language, day)
        raw = json.dumps(payload)
        if self._use_memory:
            _memory_explains[key] = raw
            return True
        if self._writes_blocked:
            return False
        try:
            await self._client.setex(key, CA_BUNDLE_TTL_SECONDS, raw)
            logger.info(f"CA explain cached: {key}")
            return True
        except Exception as e:
            if is_redis_memory_error(e):
                self._block_writes(e, "set_explain")
            else:
                logger.warning(f"CA explain cache write failed ({key}): {e}")
            return False

    async def count_ready_audio(
        self, article_count: int, day: date | None = None, language: str = "hi", *, quiet: bool = False
    ) -> int:
        bundle_day = day or self._active_bundle_day
        ready = 0
        for i in range(article_count):
            data = await self.get_explain(i, bundle_day, language, quiet=quiet)
            if data and data.get("audio_base64"):
                ready += 1
        return ready
