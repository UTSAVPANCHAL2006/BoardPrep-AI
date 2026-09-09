import json
from typing import Any

from app.agents.state import InterviewState
from app.common.logger import get_logger
from app.config.config import REDIS_URL, SESSION_TTL_SECONDS as _SESSION_TTL
from app.schema.interview import AnswerEvaluation, ChatTurn, CASource, DAFProfile, DAFFlag, EnrichedArticle, RetrievedChunk

from app.tools.ca_cache import is_redis_memory_error

logger = get_logger(__name__)

_memory_store = {}


class SessionStore:
    def __init__(self):
        self._url = REDIS_URL
        self._client = None
        self._use_memory = False

    async def connect(self):
        if self._client is not None or self._use_memory:
            return
        try:
            import redis.asyncio as redis
            self._client = redis.from_url(self._url, decode_responses=True)
            await self._client.ping()
        except Exception:
            self._use_memory = True
            self._client = None

    async def close(self):
        if self._client and not self._use_memory:
            await self._client.aclose()
        self._client = None

    def key(self, session_id):
        return f"interview:session:{session_id}"

    async def save_state(self, session_id, state):
        await self.connect()
        serializable = self.serialize_state(state)
        payload = json.dumps(serializable)
        key = self.key(session_id)
        _memory_store[key] = payload
        if self._use_memory:
            return
        try:
            await self._client.setex(key, _SESSION_TTL, payload)
        except Exception as e:
            if is_redis_memory_error(e):
                logger.warning(
                    f"Redis full — interview session kept in memory only ({session_id[:8]})"
                )
                return
            raise

    async def load_state(self, session_id):
        await self.connect()
        key = self.key(session_id)
        raw = _memory_store.get(key)
        if raw is None and not self._use_memory and self._client:
            try:
                raw = await self._client.get(key)
            except Exception as e:
                if not is_redis_memory_error(e):
                    raise
                raw = _memory_store.get(key)
        if not raw:
            return None
        return self.deserialize_state(json.loads(raw))

    def serialize_state(self, state):
        out = {}
        for key, value in state.items():
            if isinstance(value, DAFProfile):
                out[key] = value.model_dump()
            elif hasattr(value, "model_dump"):
                out[key] = value.model_dump()
            elif isinstance(value, list):
                out[key] = [item.model_dump() if hasattr(item, "model_dump") else item for item in value]
            else:
                out[key] = value
        return out

    def deserialize_state(self, data) -> InterviewState:
        if "daf_profile" in data and isinstance(data["daf_profile"], dict):
            data["daf_profile"] = DAFProfile.model_validate(data["daf_profile"])
        if "chat_history" in data:
            data["chat_history"] = [
                ChatTurn.model_validate(t) if isinstance(t, dict) else t
                for t in data.get("chat_history", [])
            ]
        if "last_evaluation" in data and isinstance(data["last_evaluation"], dict):
            data["last_evaluation"] = AnswerEvaluation.model_validate(data["last_evaluation"])
        if "daf_flags" in data:
            data["daf_flags"] = [
                DAFFlag.model_validate(f) if isinstance(f, dict) else f
                for f in data.get("daf_flags", [])
            ]
        if "last_retrieved_chunks" in data:
            data["last_retrieved_chunks"] = [
                RetrievedChunk.model_validate(c) if isinstance(c, dict) else c
                for c in data.get("last_retrieved_chunks", [])
            ]
        if "ca_articles" in data:
            data["ca_articles"] = [
                EnrichedArticle.model_validate(a) if isinstance(a, dict) else a
                for a in data.get("ca_articles", [])
            ]
        if "last_ca_source" in data and isinstance(data["last_ca_source"], dict):
            data["last_ca_source"] = CASource.model_validate(data["last_ca_source"])
        return data
