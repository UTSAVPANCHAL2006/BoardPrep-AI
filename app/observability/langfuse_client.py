"""Optional Langfuse tracing of model and voice calls; does nothing when no Langfuse keys are set."""

import os
from contextlib import contextmanager
from typing import Any, Generator

from app.common.logger import getLogger

logger = getLogger(__name__)

_langfuse = None


def langfuseHost() -> str:
    return os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")


def getLangfuse():
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    pk = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    sk = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not pk or not sk:
        return None
    try:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=pk,
            secret_key=sk,
            host=langfuseHost(),
        )
        logger.info("Langfuse client initialized")
        return _langfuse
    except Exception as e:
        logger.warning(f"Langfuse init failed: {e}")
        return None


def initLangfuse() -> bool:
    """Eager init on app startup."""
    return getLangfuse() is not None


def getLangchainHandler():
    """Return a LangChain callback handler (Langfuse v4+)."""
    if not getLangfuse():
        return None
    try:
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception as e:
        logger.warning(f"Langfuse handler failed: {e}")
        return None


def langchainInvokeConfig(
    session_id: str = "",
    run_name: str = "llm_call",
    tags: list[str] | None = None,
) -> dict:
    """Build LangChain invoke config with Langfuse callback + session metadata."""
    config: dict = {"run_name": run_name}
    handler = getLangchainHandler()
    if handler:
        config["callbacks"] = [handler]

    metadata: dict = {}
    if session_id:
        metadata["langfuse_session_id"] = session_id
        metadata["session_id"] = session_id
    if tags:
        metadata["langfuse_tags"] = tags
    if metadata:
        config["metadata"] = metadata

    return config


@contextmanager
def observationContext(
    name: str,
    session_id: str = "",
    as_type: str = "span",
    input: Any = None,
    metadata: dict | None = None,
) -> Generator[Any, None, None]:
    """Trace a non-LangChain step (STT, TTS, RAG ingest, etc.)."""
    lf = getLangfuse()
    if not lf:
        yield None
        return

    meta = dict(metadata or {})
    if session_id:
        meta["session_id"] = session_id

    try:
        with lf.start_as_current_observation(
            name=name,
            as_type=as_type,
            input=input,
            metadata=meta,
        ) as span:
            yield span
    except Exception as e:
        logger.warning(f"Langfuse observation '{name}' failed: {e}")
        yield None


def flushLangfuse():
    lf = getLangfuse()
    if lf:
        try:
            lf.flush()
        except Exception as e:
            logger.warning(f"Langfuse flush failed: {e}")
