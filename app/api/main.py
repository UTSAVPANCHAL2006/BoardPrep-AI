import asyncio
import base64
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agents.graph import InterviewGraph
from app.agents.state import InterviewState
from app.common.logger import get_logger
from app.common.timing import get_metrics, record_turn, track_step
from app.common.utils import build_daf_topic_stack
from app.config.ca_languages import CA_VOICE_LANGUAGES, DEFAULT_CA_VOICE_LANG, ca_explain_use_llm, languages_public, resolve_ca_language
from app.config.config import (
    CA_BATCH_AI_ONLY_AT_MIDNIGHT,
    CA_STARTUP_CATCHUP_ENABLED,
    DAILY_CA_ARTICLE_COUNT,
    DEFAULT_INTERVIEW_MODE,
    INTERVIEW_MODES,
    SYLLABUS_PATH,
    UPLOAD_DIR,
)
from app.tools.ca_briefing_tool import CaBriefingTool
from app.tools.ca_cache import CaCache
from app.rag.embedding import Embedding
from app.rag.ingest import Ingest
from app.rag.llm import LLM
from app.rag.retriever import Retriever
from app.schema.interview import DAFProfile
from app.tools.daf_tool import DafTool
from app.tools.news_enrich_tool import NewsEnrichTool
from app.tools.news_fetch_tool import NewsFetchTool
from app.tools.session_store import SessionStore
from app.tools.voice_tool import SttTool, TtsTool
from app.observability.langfuse_client import flush_langfuse, init_langfuse, observation_context

logger = get_logger(__name__)

llm = LLM()
embedding = Embedding()
ingest = Ingest(embedding)
retriever = Retriever(embedding)
interview_graph = None
daf_tool = None
news_fetch_tool = NewsFetchTool()
news_enrich_tool = None
ca_briefing_tool = None
stt_tool = SttTool()
tts_tool = TtsTool()
session_store = SessionStore()
ca_cache = CaCache()
_ca_prepare_lock = asyncio.Lock()
_ca_prepare_running = False
_ca_prepare_task: asyncio.Task | None = None
_ca_prewarm_lock = asyncio.Lock()
_ca_prewarm_running = False
_daily_pipeline_lock = asyncio.Lock()
_daily_pipeline_running = False
_explain_locks: dict[str, asyncio.Lock] = {}
_IST = ZoneInfo("Asia/Kolkata")


def india_today() -> date:
    from datetime import datetime

    return datetime.now(_IST).date()


async def _run_ca_prepare(session_id: str, force: bool = False) -> list:
    """Fetch + enrich today's bundle. Never raises — returns fallback on failure."""
    global _ca_prepare_running
    _ca_prepare_running = True
    try:
        articles = await prepare_current_affairs(session_id, DAFProfile(), force=force)
        if (
            articles
            and ca_bundle_is_live(articles)
            and not CA_BATCH_AI_ONLY_AT_MIDNIGHT
        ):
            needs, force_fetch_flag = await assess_daily_pipeline()
            if needs:
                asyncio.create_task(
                    schedule_full_daily_pipeline(
                        force_fetch=force_fetch_flag, force_voice=force, source="prepare"
                    )
                )
        logger.info(f"Daily CA prepare finished ({len(articles)} articles)")
        return articles
    except Exception as e:
        logger.error(f"Daily CA prepare failed: {e}")
        return get_enrich_tool().load_fallback_current_affairs()
    finally:
        _ca_prepare_running = False


async def ensure_daily_ca_bundle(session_id: str = "daily-ca", force: bool = False) -> list:
    """Block until today's CA bundle is ready. Waits on in-flight prepare instead of returning empty."""
    global _ca_prepare_task

    if force and _ca_prepare_task and not _ca_prepare_task.done():
        await _ca_prepare_task

    async with _ca_prepare_lock:
        if not force:
            cached = await ca_cache.get_bundle()
            if cached and not ca_bundle_is_stale(cached):
                return cached

        if _ca_prepare_task and not _ca_prepare_task.done():
            task = _ca_prepare_task
        else:
            _ca_prepare_task = asyncio.create_task(_run_ca_prepare(session_id, force=force))
            task = _ca_prepare_task

    articles = await task
    if not articles:
        articles = get_enrich_tool().load_fallback_current_affairs()
    return articles


async def schedule_daily_ca_prepare(session_id: str = "daily-ca", force: bool = False) -> None:
    """Kick off one background CA build — never block HTTP handlers on enrich."""
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT and not force:
        cached = await ca_cache.get_bundle()
        if cached and not ca_bundle_is_stale(cached):
            return
        if not cached:
            return
    async with _ca_prepare_lock:
        if _ca_prepare_task and not _ca_prepare_task.done():
            return
        if not force:
            cached = await ca_cache.get_bundle()
            if cached and not ca_bundle_is_stale(cached):
                return

    async def run() -> None:
        try:
            await ensure_daily_ca_bundle(session_id, force=force)
        except Exception as e:
            logger.error(f"Background daily CA prepare failed: {e}")

    asyncio.create_task(run())


async def lookup_cached_explain(article, article_index: int, language: str = DEFAULT_CA_VOICE_LANG) -> dict | None:
    lang = resolve_ca_language(language)
    cached = await ca_cache.get_explain(article_index, language=lang.code)
    if not cached or not cached.get("audio_base64"):
        return None
    cached_title = (cached.get("article_title") or "").strip().lower()
    current_title = (getattr(article, "title", "") or "").strip().lower()
    if cached_title and current_title and cached_title != current_title:
        return None
    if (cached.get("voice_language") or lang.code) != lang.code:
        return None
    return cached


async def build_and_cache_explain(
    article,
    article_index: int,
    session_id: str,
    force: bool = False,
    language: str = DEFAULT_CA_VOICE_LANG,
    use_llm: bool = True,
):
    """One article: classroom briefing + TTS in the selected language, then Redis."""
    lang = resolve_ca_language(language)
    lock_key = ca_cache.explain_key(article_index, language=lang.code)
    if lock_key not in _explain_locks:
        _explain_locks[lock_key] = asyncio.Lock()

    async with _explain_locks[lock_key]:
        if not force:
            cached = await lookup_cached_explain(article, article_index, language=lang.code)
            if cached:
                return cached, False

        briefing_tool = get_briefing_tool()
        briefing = await briefing_tool.generate_briefing(
            article, session_id, language=lang.code, use_llm=use_llm
        )
        if session_id == "daily-ca-prewarm" and briefing.get("is_fallback"):
            logger.info(
                f"CA prewarm skip — no article-specific voice ({lang.code}, index={article_index})"
            )
            return None, False
        audio = b""
        audio_error = ""
        try:
            audio = await asyncio.wait_for(
                tts_tool.synthesize(briefing["briefing_voice"], language_code=lang.tts),
                timeout=90.0,
            )
        except asyncio.TimeoutError:
            audio_error = "TTS timed out"
            logger.error(f"CA explain TTS timed out after 90s (index={article_index}, lang={lang.code})")
        except Exception as e:
            audio_error = str(e)
            logger.error(f"CA explain TTS failed (index={article_index}, lang={lang.code}): {e}")
            if "402" in audio_error or "Payment Required" in audio_error:
                raise

        payload = serialize_ca_briefing(briefing)
        if not payload:
            raise HTTPException(status_code=500, detail="Failed to generate briefing")
        payload.source = article.source or ""
        payload.source_url = article.url or ""
        payload.voice_language = lang.code
        payload.audio_base64 = base64.b64encode(audio).decode() if audio else ""
        if audio:
            payload.briefing_voice = ""
        if audio_error and not audio:
            payload.voice_error = voice_error_message(audio_error)

        dumped = payload.model_dump()
        if audio and not briefing.get("is_fallback"):
            cached_ok = await ca_cache.set_explain(article_index, dumped, language=lang.code)
            if not cached_ok and ca_cache.is_storage_full():
                logger.warning(
                    f"CA explain not cached — Redis full (index={article_index}, lang={lang.code})"
                )
        elif audio and briefing.get("is_fallback"):
            logger.warning("CA explain not cached — generic fallback voice only")
        elif audio_error:
            logger.warning(
                f"CA explain not cached — TTS failed (index={article_index}, lang={lang.code}): {audio_error}"
            )
        return dumped, True


async def _prewarm_language_voices(articles: list, language: str, *, force: bool = False) -> None:
    """Generate Aayan audio for one language (no global lock — caller owns concurrency)."""
    lang = resolve_ca_language(language)
    if not force:
        ready = await ca_cache.count_ready_audio(len(articles), language=lang.code, quiet=True)
        if ready >= len(articles):
            logger.info(f"CA voices already in Redis ({lang.code} {ready}/{len(articles)})")
            return
    for i, article in enumerate(articles):
        if ca_cache.is_storage_full():
            logger.warning(f"CA prewarm stopped — Redis storage full ({lang.code} at index {i})")
            break
        try:
            result, _ = await build_and_cache_explain(
                article, i, "daily-ca-prewarm", force=force, language=lang.code, use_llm=True
            )
            if result is None:
                continue
        except Exception as e:
            err = str(e)
            if "402" in err or "Payment Required" in err:
                logger.error(
                    "CA prewarm stopped — Sarvam TTS credits exhausted or invalid key. "
                    "Update SARVAM_API_KEY in .env (browser TTS fallback still works)."
                )
                break
            logger.error(f"CA prewarm failed for index {i} ({lang.code}): {e}")
        if i < len(articles) - 1:
            await asyncio.sleep(0.15)
    ready = await ca_cache.count_ready_audio(len(articles), language=lang.code, quiet=True)
    logger.info(f"CA auto-prewarm finished: {lang.code} {ready}/{len(articles)} audio in Redis")


async def prewarm_voices_background(
    articles: list,
    force: bool = False,
    language: str = DEFAULT_CA_VOICE_LANG,
) -> None:
    """Generate Aayan audio for each daily story in one language and store in Redis."""
    global _ca_prewarm_running
    if not articles:
        return
    async with _ca_prewarm_lock:
        if _ca_prewarm_running:
            logger.info("CA voice prewarm already running")
            return
        _ca_prewarm_running = True
    try:
        await _prewarm_language_voices(articles, language, force=force)
        flush_langfuse()
    except Exception as e:
        logger.error(f"CA auto-prewarm failed: {e}")
    finally:
        _ca_prewarm_running = False


def get_graph():
    global interview_graph, daf_tool, news_enrich_tool
    if interview_graph is None:
        daf_tool = DafTool(llm)
        news_enrich_tool = NewsEnrichTool(llm)
        interview_graph = InterviewGraph(llm, retriever)
    return interview_graph


def get_enrich_tool():
    get_graph()
    return news_enrich_tool


def get_briefing_tool():
    global ca_briefing_tool
    get_graph()
    if ca_briefing_tool is None:
        ca_briefing_tool = CaBriefingTool(llm)
    return ca_briefing_tool


def resolve_interview_mode(mode: str | None) -> dict:
    key = (mode or DEFAULT_INTERVIEW_MODE).lower()
    if key not in INTERVIEW_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interview_mode. Choose from: {', '.join(INTERVIEW_MODES)}",
        )
    return {"interview_mode": key, **INTERVIEW_MODES[key]}


def initial_state(session_id, daf_text, profile, mode_config):
    return InterviewState(
        session_id=session_id,
        candidate_daf=daf_text,
        daf_profile=profile,
        chat_history=[],
        current_question="",
        current_question_voice="",
        current_focus_anchor="",
        last_answer="",
        current_phase="daf_opening",
        topic_stack=build_daf_topic_stack(profile),
        panel_persona="UPSC board member",
        follow_up_count=0,
        phase_exchange_count=0,
        interview_complete=False,
        feedback_report={},
        router_action="pivot",
        daf_flags=[],
        last_retrieved_chunks=[],
        ca_articles=[],
        ca_article_cursor=0,
        interview_mode=mode_config["interview_mode"],
        max_questions=mode_config["max_questions"],
        exchanges_per_phase=mode_config["exchanges_per_phase"],
    )


def serialize_evaluation(evaluation):
    if not evaluation:
        return None
    if hasattr(evaluation, "model_dump"):
        return evaluation.model_dump()
    return evaluation


def serialize_daf_flags(flags):
    return [f.model_dump() if hasattr(f, "model_dump") else f for f in (flags or [])]


def voice_for_tts(state: dict) -> str:
    return state.get("current_question_voice") or state.get("current_question", "")


def serialize_ca_source(ca_source) -> "CASourceResponse | None":
    if not ca_source:
        return None
    data = ca_source.model_dump() if hasattr(ca_source, "model_dump") else ca_source
    return CASourceResponse(**data)


def serialize_chunks(chunks):
    return [c.model_dump() if hasattr(c, "model_dump") else c for c in (chunks or [])]


def serialize_ca_briefing(briefing) -> "CABriefingResponse | None":
    if not briefing:
        return None
    data = briefing.model_dump() if hasattr(briefing, "model_dump") else briefing
    if not data.get("briefing_voice") and not data.get("briefing_text"):
        return None
    return CABriefingResponse(
        article_title=data.get("article_title", ""),
        briefing_text=data.get("briefing_text", ""),
        briefing_voice=data.get("briefing_voice", ""),
        source=data.get("source", ""),
        source_url=data.get("source_url", ""),
        prelims_pointer=data.get("prelims_pointer", ""),
        mains_angle=data.get("mains_angle", ""),
        gs_link=data.get("gs_link", ""),
        interview_tip=data.get("interview_tip", ""),
        gs_tags=data.get("gs_tags", []),
        key_highlights=data.get("key_highlights", []),
        key_concepts=data.get("key_concepts", {}),
        voice_language=data.get("voice_language", DEFAULT_CA_VOICE_LANG),
    )


def voice_error_message(err: str) -> str:
    text = err or ""
    if "402" in text or "Payment Required" in text:
        return "Sarvam credits exhausted — top up at sarvam.ai (using browser voice fallback)"
    if "SARVAM_API_KEY" in text or "not set" in text.lower():
        return "SARVAM_API_KEY missing in backend .env"
    return "Sarvam voice unavailable — using browser voice fallback"


async def synthesize_briefing_audio(state: dict) -> bytes:
    briefing = state.get("last_ca_briefing") or {}
    voice = briefing.get("briefing_voice", "")
    if not voice:
        return b""
    session_id = state.get("session_id", "")
    try:
        with observation_context("ca_briefing_tts", session_id, as_type="tool", input={"chars": len(voice)}):
            return await tts_tool.synthesize(voice)
    except Exception:
        return b""


def ca_bundle_is_live(articles: list) -> bool:
    """True when bundle has real newspaper URLs (not static fallback)."""
    if not articles:
        return False
    with_url = sum(1 for a in articles if (getattr(a, "url", "") or "").startswith("http"))
    return with_url >= max(3, len(articles) // 2)


def ca_bundle_is_stale(articles: list) -> bool:
    """Invalidate cache when articles are old, wrong source, or fallback-only."""
    if not ca_bundle_is_live(articles):
        return True
    allowed = {"The Hindu", "Indian Express"}
    for a in articles:
        if (getattr(a, "source", "") or "") not in allowed:
            return True
    cutoff = (india_today() - timedelta(days=1)).isoformat()
    dates = [(a.published_at or "")[:10] for a in articles if getattr(a, "published_at", None)]
    if not dates:
        return True
    return all(d < cutoff for d in dates if d)


async def prepare_current_affairs(session_id, profile, force: bool = False):
    """Build shared daily CA bundle — 8–10 curated newspaper headlines."""
    enrich_tool = get_enrich_tool()
    if force:
        await ca_cache.delete_bundle()
        cached = None
    else:
        cached = await ca_cache.get_bundle()
    if cached and ca_bundle_is_stale(cached):
        await ca_cache.delete_bundle()
        cached = None
    if cached:
        enriched = cached
        logger.info(f"Using Redis daily CA bundle ({len(enriched)} articles)")
    elif CA_BATCH_AI_ONLY_AT_MIDNIGHT and not force:
        enriched = enrich_tool.load_fallback_current_affairs()
        logger.info(
            f"Daily CA using fallback until 12 AM IST fetch ({len(enriched)} articles)"
        )
    else:
        try:
            with observation_context("ca_fetch_daily", session_id, as_type="tool"):
                raw = await news_fetch_tool.fetch_daily_upsc_bundle(DAILY_CA_ARTICLE_COUNT)
            with observation_context(
                "ca_enrich_articles",
                session_id,
                as_type="chain",
                input={"count": len(raw)},
            ):
                enriched = await enrich_tool.enrich_articles(raw, session_id=session_id, daily=True)
            if len(enriched) < 5:
                enriched = enrich_tool.load_fallback_current_affairs()
            if ca_bundle_is_live(enriched):
                await ca_cache.set_bundle(enriched)
            else:
                logger.warning("Daily CA: fallback bundle — not caching")
        except Exception as e:
            logger.error(f"Daily CA prepare failed, using fallback: {e}")
            enriched = enrich_tool.load_fallback_current_affairs()

    if not enriched:
        enriched = enrich_tool.load_fallback_current_affairs()

    with observation_context("ca_chroma_ingest", session_id, as_type="tool", input={"articles": len(enriched)}):
        ingest.ingest_shared_current_affairs(enriched)
    flush_langfuse()
    return enriched


async def count_languages_ready(articles: list) -> dict[str, int]:
    if not articles:
        return {}
    ready: dict[str, int] = {}
    for lang in CA_VOICE_LANGUAGES:
        ready[lang.code] = await ca_cache.count_ready_audio(len(articles), language=lang.code)
    return ready


async def all_languages_ready(articles: list) -> bool:
    if not articles:
        return False
    ready = await count_languages_ready(articles)
    return all(ready.get(lang.code, 0) >= len(articles) for lang in CA_VOICE_LANGUAGES)


async def prewarm_all_languages_background(
    articles: list, force: bool = False, *, midnight_job: bool = False
) -> None:
    """Prewarm every supported CA voice language into Redis (midnight batch job)."""
    global _ca_prewarm_running
    if not articles:
        return
    async with _ca_prewarm_lock:
        if _ca_prewarm_running:
            logger.info("CA batch prewarm skipped — single-language prewarm in progress")
            return
        _ca_prewarm_running = True
    try:
        for lang in CA_VOICE_LANGUAGES:
            if ca_cache.is_storage_full():
                logger.error("CA batch prewarm aborted — Redis storage full")
                break
            if CA_BATCH_AI_ONLY_AT_MIDNIGHT and not midnight_job and lang.code not in ("hi", "en"):
                logger.info(f"CA batch prewarm deferred until 12 AM IST: {lang.name} ({lang.code})")
                continue
            logger.info(f"CA batch prewarm starting: {lang.name} ({lang.code})")
            await _prewarm_language_voices(articles, lang.code, force=force)
        ready = await count_languages_ready(articles)
        logger.info(f"CA batch prewarm summary: {ready}")
        flush_langfuse()
    except Exception as e:
        logger.error(f"CA batch prewarm failed: {e}")
    finally:
        _ca_prewarm_running = False


async def assess_daily_pipeline() -> tuple[bool, bool]:
    """Return (needs_run, force_fetch). force_fetch=True only when bundle missing or stale."""
    today = india_today()
    if await ca_cache.is_daily_pipeline_done(day=today):
        return False, False
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT:
        return False, False
    cached = await ca_cache.get_bundle(day=today)
    if not cached or ca_bundle_is_stale(cached):
        return True, True
    if not await all_languages_ready(cached):
        return True, False
    await ca_cache.mark_daily_pipeline_done(day=today)
    return False, False


async def run_midnight_ca_pipeline(*, force_fetch: bool = True) -> None:
    """Fresh newspaper fetch (optional) + all 11 language voices in Redis."""
    if force_fetch:
        articles = await ensure_daily_ca_bundle("midnight-ist", force=True)
    else:
        articles = await ca_cache.get_bundle()
        if not articles or ca_bundle_is_stale(articles):
            articles = await ensure_daily_ca_bundle("midnight-ist", force=False)
    await prewarm_all_languages_background(articles, force=False, midnight_job=True)


async def schedule_full_daily_pipeline(
    *,
    force_fetch: bool = False,
    force_voice: bool = False,
    source: str = "auto",
) -> bool:
    """Run fetch + 11-language prewarm in background. Returns False if already running or done today."""
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT and source not in ("midnight", "manual"):
        logger.info(f"Daily CA pipeline deferred until 12 AM IST (source={source})")
        return False
    if force_fetch or force_voice:
        await ca_cache.clear_daily_pipeline_done()
    else:
        needs, _ = await assess_daily_pipeline()
        if not needs:
            logger.info("Daily CA pipeline already finished for today — skipping")
            return False

    global _daily_pipeline_running
    async with _daily_pipeline_lock:
        if _daily_pipeline_running:
            logger.info("Daily CA pipeline already running")
            return False
        _daily_pipeline_running = True

    async def run() -> None:
        global _daily_pipeline_running
        try:
            if ca_cache.is_storage_full():
                logger.error("Daily CA pipeline skipped — Redis storage full")
                return
            logger.info(f"Daily CA pipeline started (fetch={force_fetch}, force_voice={force_voice})")
            if force_fetch:
                articles = await ensure_daily_ca_bundle("manual-pipeline", force=True)
            else:
                articles = await ca_cache.get_bundle()
                if not articles or ca_bundle_is_stale(articles):
                    articles = await ensure_daily_ca_bundle("manual-pipeline", force=False)
            midnight_job = source in ("midnight", "manual")
            await prewarm_all_languages_background(
                articles, force=force_voice, midnight_job=midnight_job
            )
            if ca_cache.is_storage_full():
                logger.error("Daily CA pipeline stopped early — Redis storage full")
                return
            articles = await ca_cache.get_bundle() or articles
            if articles and await all_languages_ready(articles):
                await ca_cache.mark_daily_pipeline_done()
            logger.info("Daily CA pipeline completed")
        except Exception as e:
            logger.error(f"Daily CA pipeline failed: {e}")
        finally:
            _daily_pipeline_running = False

    asyncio.create_task(run())
    return True


async def prefetch_daily_ca_startup():
    """Load today's newspaper bundle in background; voices handled by daily pipeline scheduler."""
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT:
        logger.info("Daily CA startup fetch skipped — fresh fetch runs at 12:00 AM IST only")
        return
    try:
        asyncio.create_task(ensure_daily_ca_bundle("startup", force=False))
        logger.info("Daily CA bundle prefetch scheduled on startup")
    except Exception as e:
        logger.error(f"Daily CA startup prefetch failed: {e}")


async def preserve_today_ca_cache():
    """Keep existing Redis CA — stop batch LLM/TTS until midnight IST job."""
    await asyncio.sleep(9)
    try:
        cached = await ca_cache.get_bundle()
        if not cached or ca_bundle_is_stale(cached):
            logger.info("No live CA bundle in Redis — waiting for 12 AM IST fetch")
            return
        ready = await count_languages_ready(cached)
        await ca_cache.mark_daily_pipeline_done()
        logger.info(
            f"CA cache preserved for today — batch Redis writes paused until 12 AM IST: {ready}"
        )
    except Exception as e:
        logger.warning(f"CA cache preserve check failed: {e}")


async def prefetch_ca_background(session_id: str):
    """Attach shared daily CA bundle to session — reuses global prepare task, no duplicate fetch."""
    try:
        articles = await ensure_daily_ca_bundle(session_id, force=False)
        state = await session_store.load_state(session_id)
        if not state:
            return
        state["ca_articles"] = articles
        state["ca_prefetch_ready"] = True
        await session_store.save_state(session_id, state)
        logger.info(f"CA prefetch done for {session_id[:8]}: {len(articles)} articles")
        flush_langfuse()
    except Exception as e:
        logger.error(f"CA prefetch failed: {e}")


async def lifespan(app: FastAPI):
    if init_langfuse():
        logger.info("Langfuse tracing enabled")
    try:
        ingest.ingest_shared_syllabus(SYLLABUS_PATH)
    except Exception as e:
        logger.error(f"Syllabus ingest failed (RAG may be degraded): {e}")
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT:
        asyncio.create_task(preserve_today_ca_cache())
    else:
        asyncio.create_task(prefetch_daily_ca_startup())
    from app.tools.ca_daily_scheduler import start_midnight_ca_scheduler

    asyncio.create_task(
        start_midnight_ca_scheduler(
            assess_pipeline=assess_daily_pipeline,
            schedule_pipeline=schedule_full_daily_pipeline,
            ca_cache=ca_cache,
            startup_catchup=CA_STARTUP_CATCHUP_ENABLED and not CA_BATCH_AI_ONLY_AT_MIDNIGHT,
        )
    )
    yield
    flush_langfuse()
    await session_store.close()


app = FastAPI(title="UPSC Mock Interview Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class UploadDAFResponse(BaseModel):
    session_id: str
    daf_profile: DAFProfile


class EvaluationResponse(BaseModel):
    clarity: str
    factual_consistency: str
    notes: str


class DAFFlagResponse(BaseModel):
    field: str
    daf_says: str
    candidate_said: str
    message: str


class RetrievedChunkResponse(BaseModel):
    doc_type: str
    text: str
    preview: str
    source_title: str = ""


class CASourceResponse(BaseModel):
    title: str
    daf_anchor: str = ""
    source: str = ""
    grounded: bool = False
    grounding_score: float = 0.0


class CABriefingResponse(BaseModel):
    article_title: str
    briefing_text: str
    briefing_voice: str = ""
    source: str = ""
    source_url: str = ""
    prelims_pointer: str = ""
    mains_angle: str = ""
    gs_link: str = ""
    interview_tip: str = ""
    gs_tags: list[str] = Field(default_factory=list)
    key_highlights: list[str] = Field(default_factory=list)
    key_concepts: dict[str, str] = Field(default_factory=dict)
    audio_base64: str = ""
    voice_error: str = ""
    voice_language: str = DEFAULT_CA_VOICE_LANG


class EnrichedArticleResponse(BaseModel):
    title: str
    source: str = ""
    published_at: str = ""
    url: str = ""
    daf_anchor: str = ""
    key_highlights: list[str] = Field(default_factory=list)
    detailed_insights: str = ""
    key_concepts: dict[str, str] = Field(default_factory=dict)
    gs_tags: list[str] = Field(default_factory=list)
    is_prelims_relevant: bool = False


class DailyCAResponse(BaseModel):
    articles: list[EnrichedArticleResponse]
    personalized: bool = False
    edition_date: str = ""
    is_live: bool = False
    is_fallback: bool = False
    is_preparing: bool = False
    article_count: int = 0
    voices_ready: int = 0
    voices_total: int = 0


class StartInterviewResponse(BaseModel):
    session_id: str
    question: str
    audio_base64: str
    current_phase: str
    articles_indexed: int
    interview_mode: str
    router_action: str
    daf_focus: str = ""
    retrieved_chunks: list[RetrievedChunkResponse] = Field(default_factory=list)
    ca_source: CASourceResponse | None = None
    ca_briefing: CABriefingResponse | None = None


def build_start_interview_response(
    session_id: str,
    state: dict,
    enriched: list,
    question_audio: bytes,
    briefing_audio: bytes = b"",
) -> StartInterviewResponse:
    ca_briefing = serialize_ca_briefing(state.get("last_ca_briefing"))
    if ca_briefing and briefing_audio:
        ca_briefing.audio_base64 = base64.b64encode(briefing_audio).decode()
    return StartInterviewResponse(
        session_id=session_id,
        question=state.get("current_question", ""),
        audio_base64=base64.b64encode(question_audio).decode() if question_audio else "",
        current_phase=state.get("current_phase", "daf_opening"),
        articles_indexed=len(enriched),
        interview_mode=state.get("interview_mode", "full"),
        router_action=state.get("router_action", "pivot"),
        daf_focus=state.get("current_focus_anchor", ""),
        retrieved_chunks=serialize_chunks(state.get("last_retrieved_chunks", [])),
        ca_source=serialize_ca_source(state.get("last_ca_source")),
        ca_briefing=ca_briefing,
    )


class RespondResponse(BaseModel):
    session_id: str
    transcript: str
    question: str
    audio_base64: str
    current_phase: str
    interview_complete: bool
    evaluation_notes: str
    evaluation: EvaluationResponse | None = None
    router_action: str = "pivot"
    daf_flags: list[DAFFlagResponse] = Field(default_factory=list)
    daf_focus: str = ""
    retrieved_chunks: list[RetrievedChunkResponse] = Field(default_factory=list)
    ca_source: CASourceResponse | None = None
    ca_briefing: CABriefingResponse | None = None


async def resolve_ca_articles(session_id: str | None, profile: DAFProfile) -> tuple[list, bool]:
    """Return CA articles and whether they are a live newspaper bundle."""
    cached = await ca_cache.get_bundle()
    if cached and not ca_bundle_is_stale(cached):
        return cached, ca_bundle_is_live(cached)
    if session_id:
        state = await session_store.load_state(session_id)
        if state and state.get("ca_articles"):
            articles = state["ca_articles"]
            if ca_bundle_is_live(articles):
                return articles, True
    if _ca_prepare_task and not _ca_prepare_task.done():
        stale = await ca_cache.get_bundle()
        if stale:
            return stale, ca_bundle_is_live(stale)
        fallback = get_enrich_tool().load_fallback_current_affairs()
        return fallback, False
    fallback = get_enrich_tool().load_fallback_current_affairs()
    return fallback, False


@app.get("/health")
async def health():
    return {"ok": True, "ca_preparing": _ca_prepare_running}


@app.get("/current-affairs/daily", response_model=DailyCAResponse)
async def daily_current_affairs(session_id: str | None = None, refresh: bool = False):
    profile = DAFProfile()
    personalized = False
    if session_id:
        state = await session_store.load_state(session_id)
        if state:
            profile = state["daf_profile"]
            personalized = True

    sid = session_id or "daily-ca"
    if refresh:
        articles = await ensure_daily_ca_bundle(sid, force=True)
        is_live = ca_bundle_is_live(articles)
    else:
        articles, is_live = await resolve_ca_articles(session_id, profile)
        if not is_live:
            await schedule_daily_ca_prepare(sid, force=False)

    edition_date = india_today().strftime("%d %b %Y")
    voices_ready = 0
    if articles:
        voices_ready = await ca_cache.count_ready_audio(len(articles), language=DEFAULT_CA_VOICE_LANG)
    return DailyCAResponse(
        articles=[EnrichedArticleResponse(**a.model_dump()) for a in articles],
        personalized=personalized,
        edition_date=edition_date,
        is_live=is_live,
        is_fallback=not is_live,
        is_preparing=_ca_prepare_running and not is_live,
        article_count=len(articles),
        voices_ready=voices_ready,
        voices_total=len(articles),
    )


@app.get("/current-affairs/languages")
async def current_affairs_languages():
    return {"default": DEFAULT_CA_VOICE_LANG, "languages": languages_public()}


@app.get("/current-affairs/explain-cached", response_model=CABriefingResponse)
async def explain_current_affair_cached(
    article_index: int,
    session_id: str | None = None,
    language: str = DEFAULT_CA_VOICE_LANG,
):
    """Fast path — return prewarmed voice from Redis only (no LLM/TTS)."""
    profile = DAFProfile()
    if session_id:
        state = await session_store.load_state(session_id)
        if state:
            profile = state["daf_profile"]
    articles, _ = await resolve_ca_articles(session_id, profile)
    if article_index < 0 or article_index >= len(articles):
        raise HTTPException(status_code=400, detail="Invalid article_index")
    cached = await lookup_cached_explain(articles[article_index], article_index, language=language)
    if not cached:
        raise HTTPException(status_code=404, detail="Voice not ready yet")
    return CABriefingResponse(**cached)


@app.post("/current-affairs/explain", response_model=CABriefingResponse)
async def explain_current_affair(
    article_index: int = Form(...),
    session_id: str = Form(""),
    language: str = Form(DEFAULT_CA_VOICE_LANG),
):
    profile = DAFProfile()
    sid = session_id or "daily-ca"
    if session_id:
        state = await session_store.load_state(session_id)
        if state:
            profile = state["daf_profile"]
    articles, _ = await resolve_ca_articles(session_id or None, profile)
    if article_index < 0 or article_index >= len(articles):
        raise HTTPException(status_code=400, detail="Invalid article_index")

    dumped, from_cache = await build_and_cache_explain(
        articles[article_index],
        article_index,
        sid,
        language=language,
        use_llm=ca_explain_use_llm(resolve_ca_language(language)),
    )
    if from_cache:
        logger.info(f"CA explain instant cache hit (index={article_index}, lang={language})")
    flush_langfuse()
    return CABriefingResponse(**dumped)


class PrewarmStatusResponse(BaseModel):
    articles: int
    audio_ready: int
    prewarm_running: bool
    pipeline_running: bool = False
    pipeline_done_today: bool = False
    redis_storage_full: bool = False
    languages_ready: dict[str, int] = Field(default_factory=dict)
    cache_backend: str = ""


class ClearCACacheResponse(BaseModel):
    deleted_bundles: int
    deleted_explains: int
    refreshed: bool = False


class DailyPipelineResponse(BaseModel):
    status: str
    message: str = ""
    languages_ready: dict[str, int] = Field(default_factory=dict)
    articles: int = 0


@app.post("/current-affairs/run-daily-pipeline", response_model=DailyPipelineResponse)
async def run_daily_pipeline_now(fetch: bool = Form(False), force_voice: bool = Form(False)):
    """Run 11-language Redis prewarm now. Set fetch=true to refresh today's newspaper bundle first."""
    articles = await ca_cache.get_bundle() or []
    ready = await count_languages_ready(articles)
    if not fetch and not force_voice and await ca_cache.is_daily_pipeline_done():
        return DailyPipelineResponse(
            status="already_done",
            message="Today's 11-language CA pipeline already finished",
            languages_ready=ready,
            articles=len(articles),
        )
    started = await schedule_full_daily_pipeline(
        force_fetch=fetch, force_voice=force_voice, source="manual"
    )
    if not started:
        if _daily_pipeline_running:
            msg = "Daily CA pipeline is already in progress"
            status = "already_running"
        else:
            msg = "Today's CA pipeline already finished — use fetch=true or force_voice=true to rerun"
            status = "already_done"
        return DailyPipelineResponse(
            status=status,
            message=msg,
            languages_ready=ready,
            articles=len(articles),
        )
    return DailyPipelineResponse(
        status="started",
        message="Fetch + 11-language prewarm running in background",
        languages_ready=ready,
        articles=len(articles),
    )


@app.post("/current-affairs/clear-cache", response_model=ClearCACacheResponse)
async def clear_ca_cache(refresh: bool = Form(False)):
    """Wipe Redis CA articles + cached Hindi/English voice briefings. Use refresh=true to rebuild."""
    deleted = await ca_cache.clear_all()
    refreshed = False
    if refresh:
        await schedule_full_daily_pipeline(force_fetch=True, force_voice=True, source="manual")
        refreshed = True
    return ClearCACacheResponse(
        deleted_bundles=deleted["bundles"],
        deleted_explains=deleted["explains"],
        refreshed=refreshed,
    )


@app.get("/current-affairs/prewarm-status", response_model=PrewarmStatusResponse)
async def prewarm_status(language: str = DEFAULT_CA_VOICE_LANG):
    lang = resolve_ca_language(language)
    articles = await ca_cache.get_bundle() or []
    langs_ready = await count_languages_ready(articles)
    ready = langs_ready.get(lang.code, 0) if articles else 0
    return PrewarmStatusResponse(
        articles=len(articles),
        audio_ready=ready,
        prewarm_running=_ca_prewarm_running,
        pipeline_running=_daily_pipeline_running,
        pipeline_done_today=await ca_cache.is_daily_pipeline_done(),
        redis_storage_full=ca_cache.is_storage_full(),
        languages_ready=langs_ready,
        cache_backend="memory" if ca_cache._use_memory else "redis",
    )


@app.post("/current-affairs/prewarm", response_model=PrewarmStatusResponse)
async def prewarm_daily_ca_audio(
    force: bool = Form(False),
    language: str = Form(DEFAULT_CA_VOICE_LANG),
):
    """Generate missing (or all, if force) daily CA voices into Redis for one language."""
    lang = resolve_ca_language(language)
    articles, _ = await resolve_ca_articles(None, DAFProfile())
    if not articles:
        raise HTTPException(status_code=503, detail="No current-affairs articles to prewarm")
    if CA_BATCH_AI_ONLY_AT_MIDNIGHT and not force:
        ready = await ca_cache.count_ready_audio(len(articles), language=lang.code)
        return PrewarmStatusResponse(
            articles=len(articles),
            audio_ready=ready,
            prewarm_running=False,
            pipeline_running=_daily_pipeline_running,
            pipeline_done_today=await ca_cache.is_daily_pipeline_done(),
            redis_storage_full=ca_cache.is_storage_full(),
            languages_ready=await count_languages_ready(articles),
            cache_backend="memory" if ca_cache._use_memory else "redis",
        )
    await prewarm_voices_background(articles, force=force, language=lang.code)
    ready = await ca_cache.count_ready_audio(len(articles), language=lang.code)
    return PrewarmStatusResponse(
        articles=len(articles),
        audio_ready=ready,
        prewarm_running=_ca_prewarm_running,
        cache_backend="memory" if ca_cache._use_memory else "redis",
    )


@app.post("/upload-daf", response_model=UploadDAFResponse)
async def upload_daf(
    file: UploadFile = File(...),
    interview_mode: str = Form(DEFAULT_INTERVIEW_MODE),
):
    get_graph()
    mode_config = resolve_interview_mode(interview_mode)
    session_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{session_id}.pdf"
    content = await file.read()
    dest.write_bytes(content)
    try:
        daf_text = daf_tool.extract_text_from_pdf(dest)
        with observation_context("daf_extraction", session_id, as_type="chain"):
            profile = daf_tool.extract_daf_fields(dest, raw_text=daf_text, session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    state = initial_state(session_id, daf_text, profile, mode_config)
    await session_store.save_state(session_id, dict(state))
    asyncio.create_task(prefetch_ca_background(session_id))
    flush_langfuse()
    return UploadDAFResponse(session_id=session_id, daf_profile=profile)


@app.post("/start-interview", response_model=StartInterviewResponse)
async def start_interview(session_id: str = Form(...)):
    state = await session_store.load_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found. Upload a DAF first.")

    enriched = state.get("ca_articles") or []
    if state.get("interview_started") and state.get("current_question"):
        logger.info(f"Interview already started for {session_id[:8]} — returning cached first question")
        cached_q_audio = state.get("start_audio_base64") or ""
        cached_b_audio = state.get("start_briefing_audio_base64") or ""
        return build_start_interview_response(
            session_id,
            state,
            enriched,
            base64.b64decode(cached_q_audio) if cached_q_audio else b"",
            base64.b64decode(cached_b_audio) if cached_b_audio else b"",
        )

    profile = state["daf_profile"]
    ingest.ingest_shared_syllabus(SYLLABUS_PATH)

    cached_bundle = await ca_cache.get_bundle()
    if cached_bundle and not ca_bundle_is_stale(cached_bundle):
        enriched = cached_bundle
        state["ca_articles"] = enriched
        state["ca_prefetch_ready"] = True
    elif state.get("ca_prefetch_ready") and state.get("ca_articles"):
        enriched = state["ca_articles"]
        logger.info(f"Using prefetched CA for {session_id[:8]}")
    else:
        # First question is DAF opening — do not block on CA enrich (2+ min)
        if not state.get("ca_prefetch_ready"):
            asyncio.create_task(prefetch_ca_background(session_id))
        enriched = state.get("ca_articles") or []
        logger.info(f"Starting interview without waiting for CA enrich ({session_id[:8]})")

    state["ca_article_cursor"] = 0
    with track_step(session_id, "first_question"):
        with observation_context("interview_first_question", session_id, as_type="chain"):
            graph = get_graph()
            result = await graph.run_first_question(state)
    state.update(result)
    briefing_audio = b""
    if state.get("current_phase") == "current_affairs" and state.get("last_ca_briefing"):
        with track_step(session_id, "ca_briefing_tts"):
            briefing_audio = await synthesize_briefing_audio(state)
    audio_out = b""
    with track_step(session_id, "tts"):
        try:
            with observation_context("tts_synthesize", session_id, as_type="tool", input={"chars": len(voice_for_tts(state))}):
                audio_out = await tts_tool.synthesize(voice_for_tts(state))
        except Exception:
            audio_out = b""
    state["interview_started"] = True
    state["start_audio_base64"] = base64.b64encode(audio_out).decode() if audio_out else ""
    if briefing_audio:
        state["start_briefing_audio_base64"] = base64.b64encode(briefing_audio).decode()
    record_turn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.save_state(session_id, state)
    flush_langfuse()
    return build_start_interview_response(session_id, state, enriched, audio_out, briefing_audio)


@app.post("/respond", response_model=RespondResponse)
async def respond(session_id: str = Form(...), audio: UploadFile = File(None), text_answer: str = Form(None)):
    state = await session_store.load_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    if text_answer:
        transcript = text_answer
    elif audio:
        with track_step(session_id, "stt"):
            audio_bytes = await audio.read()
            with observation_context("stt_transcribe", session_id, as_type="tool", input={"bytes": len(audio_bytes)}):
                transcript = await stt_tool.transcribe(audio_bytes, audio.content_type or "audio/wav")
    else:
        raise HTTPException(status_code=400, detail="Provide audio or text_answer")
    state["last_answer"] = transcript
    graph = get_graph()
    with track_step(session_id, "llm_turn"):
        with observation_context("interview_turn", session_id, as_type="chain", input={"transcript_len": len(transcript)}):
            result = await graph.run_turn(state)
    state.update(result)
    interview_complete = bool(state.get("interview_complete"))
    question = "" if interview_complete else state.get("current_question", "")
    audio_out = b""
    briefing_audio = b""
    if question and state.get("current_phase") == "current_affairs" and state.get("last_ca_briefing"):
        with track_step(session_id, "ca_briefing_tts"):
            briefing_audio = await synthesize_briefing_audio(state)
    if question:
        with track_step(session_id, "tts"):
            try:
                with observation_context("tts_synthesize", session_id, as_type="tool", input={"chars": len(voice_for_tts(state))}):
                    audio_out = await tts_tool.synthesize(voice_for_tts(state))
            except Exception:
                audio_out = b""
    record_turn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.save_state(session_id, state)
    flush_langfuse()
    evaluation = state.get("last_evaluation")
    notes = evaluation.notes if hasattr(evaluation, "notes") else ""
    eval_payload = serialize_evaluation(evaluation)
    ca_briefing = serialize_ca_briefing(state.get("last_ca_briefing"))
    if ca_briefing and briefing_audio:
        ca_briefing.audio_base64 = base64.b64encode(briefing_audio).decode()
    return RespondResponse(
        session_id=session_id,
        transcript=transcript,
        question=question,
        audio_base64=base64.b64encode(audio_out).decode() if audio_out else "",
        current_phase=state.get("current_phase", "daf_opening"),
        interview_complete=interview_complete,
        evaluation_notes=notes,
        evaluation=EvaluationResponse(**eval_payload) if eval_payload else None,
        router_action=state.get("router_action", "pivot"),
        daf_flags=serialize_daf_flags(state.get("daf_flags", [])),
        daf_focus=state.get("current_focus_anchor", ""),
        retrieved_chunks=serialize_chunks(state.get("last_retrieved_chunks", [])),
        ca_source=serialize_ca_source(state.get("last_ca_source")),
        ca_briefing=ca_briefing,
    )


@app.post("/respond-stream")
async def respond_stream(
    session_id: str = Form(...),
    audio: UploadFile = File(None),
    text_answer: str = Form(None),
):
    """Server-Sent Events: metadata after the turn, then TTS chunks as each sentence is synthesized."""
    from fastapi.responses import StreamingResponse
    import json

    state = await session_store.load_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if text_answer:
        transcript = text_answer
    elif audio:
        with track_step(session_id, "stt"):
            audio_bytes = await audio.read()
            with observation_context("stt_transcribe", session_id, as_type="tool", input={"bytes": len(audio_bytes)}):
                transcript = await stt_tool.transcribe(audio_bytes, audio.content_type or "audio/wav")
    else:
        raise HTTPException(status_code=400, detail="Provide audio or text_answer")

    state["last_answer"] = transcript
    graph = get_graph()
    with track_step(session_id, "llm_turn"):
        with observation_context("interview_turn", session_id, as_type="chain", input={"transcript_len": len(transcript)}):
            result = await graph.run_turn(state)
    state.update(result)
    interview_complete = bool(state.get("interview_complete"))
    question = "" if interview_complete else state.get("current_question", "")
    record_turn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.save_state(session_id, state)
    flush_langfuse()

    voice_text = voice_for_tts(state)
    evaluation = state.get("last_evaluation")
    notes = evaluation.notes if hasattr(evaluation, "notes") else ""
    eval_payload = serialize_evaluation(evaluation)
    ca_briefing = serialize_ca_briefing(state.get("last_ca_briefing"))

    async def event_generator():
        meta = {
            "type": "metadata",
            "session_id": session_id,
            "transcript": transcript,
            "question": question,
            "current_phase": state.get("current_phase"),
            "interview_complete": interview_complete,
            "router_action": state.get("router_action", "pivot"),
            "daf_flags": serialize_daf_flags(state.get("daf_flags", [])),
            "daf_focus": state.get("current_focus_anchor", ""),
            "retrieved_chunks": serialize_chunks(state.get("last_retrieved_chunks", [])),
            "ca_source": serialize_ca_source(state.get("last_ca_source")),
            "ca_briefing": ca_briefing.model_dump() if ca_briefing else None,
            "evaluation_notes": notes,
            "evaluation": eval_payload,
        }
        yield f"data: {json.dumps(meta, default=str)}\n\n"

        if question and state.get("current_phase") == "current_affairs" and state.get("last_ca_briefing"):
            with track_step(session_id, "ca_briefing_tts"):
                briefing_audio = await synthesize_briefing_audio(state)
            if briefing_audio and ca_briefing:
                ca_briefing.audio_base64 = base64.b64encode(briefing_audio).decode()
                yield f"data: {json.dumps({'type': 'briefing_audio', 'audio_base64': ca_briefing.audio_base64})}\n\n"

        if voice_text:
            with track_step(session_id, "tts_stream"):
                async for chunk in tts_tool.synthesize_stream(voice_text):
                    event_data = {"type": "audio_chunk", **chunk}
                    yield f"data: {json.dumps(event_data)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )



@app.get("/feedback-report/{session_id}")
async def feedback_report(session_id: str):
    state = await session_store.load_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    report = state.get("feedback_report")
    if not report:
        raise HTTPException(status_code=400, detail="Interview not complete yet")
    return {
        "session_id": session_id,
        "report": report,
        "daf_flags": serialize_daf_flags(state.get("daf_flags", [])),
        "interview_mode": state.get("interview_mode", "full"),
    }


@app.get("/metrics/{session_id}")
async def metrics(session_id: str):
    return get_metrics(session_id)
