"""The HTTP API the web app talks to: upload a DAF, start the interview, answer (text or voice), get the report."""

import asyncio
import base64
import random
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agents.graph import InterviewGraph
from app.api.limits import limitRequests
from app.agents.state import InterviewState
from app.common.logger import getLogger
from app.common.timing import getMetrics, recordTurn, trackStep
from app.common.utils import buildClosingAngles, buildDafTopicStack, caBoardQuestionWordLimits, sanitizeCaBoardQuestion
from app.config.ca_languages import DEFAULT_CA_VOICE_LANG
from app.config.config import (
    DEFAULT_INTERVIEW_MODE,
    INTERVIEW_MODES,
    INTERVIEW_TTS_LANGUAGE,
    SYLLABUS_PATH,
    UPLOAD_DIR,
)
from app.rag.embedding import Embedding
from app.rag.ingest import Ingest
from app.rag.llm import LLM
from app.rag.retriever import Retriever
from app.schema.interview import DAFProfile
from app.tools.daf_tool import DafTool
from app.tools.news_enrich_tool import NewsEnrichTool
from app.tools.session_store import SessionStore
from app.tools.voice_tool import SttTool, TtsTool, concatWav, isSilent
from app.observability.langfuse_client import flushLangfuse, initLangfuse, observationContext

logger = getLogger(__name__)

llm = LLM()
embedding = Embedding()
ingest = Ingest(embedding)
retriever = Retriever(embedding)
interview_graph = None
daf_tool = None
news_enrich_tool = None
stt_tool = SttTool()
tts_tool = TtsTool()
session_store = SessionStore()
_ca_prepare_task: asyncio.Task | None = None
_explain_locks: dict[str, asyncio.Lock] = {}


def getGraph():
    global interview_graph, daf_tool, news_enrich_tool
    if interview_graph is None:
        daf_tool = DafTool(llm)
        news_enrich_tool = NewsEnrichTool(llm)
        interview_graph = InterviewGraph(llm, retriever)
    return interview_graph


def getEnrichTool():
    getGraph()
    return news_enrich_tool


async def transcribeAnswer(audio_bytes: bytes, content_type: str) -> str:
    """The spoken answer as text, or a clear message the candidate can act on (never a server error)."""
    if isSilent(audio_bytes):
        raise HTTPException(status_code=400, detail="We didn't hear anything. Please speak a little louder, or type your answer.")
    try:
        return await stt_tool.transcribe(audio_bytes, content_type)
    except Exception as error:
        logger.warning(f"Speech-to-text failed: {error}")
        raise HTTPException(status_code=400, detail="We couldn't read that recording. Please record your answer again.") from error


def looksLikeDaf(profile: DAFProfile) -> bool:
    """A UPSC DAF gives at least two of: hometown, education, hobbies, optional subject. A resume or a random PDF
    does not, and an interview built on an empty profile would ask nonsense questions."""
    found = [profile.hometown, profile.education, profile.hobbies, profile.optional_subject]
    return sum(1 for item in found if item) >= 2


def resolveInterviewMode(mode: str | None) -> dict:
    key = (mode or DEFAULT_INTERVIEW_MODE).lower()
    if key not in INTERVIEW_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interview_mode. Choose from: {', '.join(INTERVIEW_MODES)}",
        )
    return {"interview_mode": key, **INTERVIEW_MODES[key]}


def initialState(session_id, daf_text, profile, mode_config):
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
        topic_stack=buildDafTopicStack(profile),
        panel_persona="UPSC board member",
        follow_up_count=0,
        phase_exchange_count=0,
        evaluation_log=[],
        interview_complete=False,
        feedback_report={},
        router_action="pivot",
        daf_flags=[],
        last_retrieved_chunks=[],
        ca_articles=[],
        ca_article_cursor=0,
        closing_angle_index=0,
        interview_mode=mode_config["interview_mode"],
        max_questions=mode_config["max_questions"],
        exchanges_per_phase=mode_config["exchanges_per_phase"],
        phase_exchanges=mode_config.get("phase_exchanges", {}),
    )


def serializeEvaluation(evaluation):
    if not evaluation:
        return None
    if hasattr(evaluation, "model_dump"):
        return evaluation.model_dump()
    return evaluation


def serializeDafFlags(flags):
    return [f.model_dump() if hasattr(f, "model_dump") else f for f in (flags or [])]


def voiceForTts(state: dict) -> str:
    """Spoken board voice — Hindi/Hinglish; on-screen text stays English in current_question."""
    raw = (state.get("current_question_voice") or state.get("current_question") or "").strip()
    if state.get("current_phase") == "current_affairs":
        cap = caBoardQuestionWordLimits(state.get("interview_mode", "full"), for_voice=True)
        return sanitizeCaBoardQuestion(raw, max_words=cap)
    return raw


def serializeCaSource(ca_source) -> "CASourceResponse | None":
    if not ca_source:
        return None
    data = ca_source.model_dump() if hasattr(ca_source, "model_dump") else ca_source
    return CASourceResponse(**data)


def serializeChunks(chunks):
    return [c.model_dump() if hasattr(c, "model_dump") else c for c in (chunks or [])]


def serializeCaBriefing(briefing) -> "CABriefingResponse | None":
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


_saved_articles: list = []


def loadSavedArticles() -> list:
    """The interview's current-affairs round asks about a saved set of curated newspaper stories. No live news
    fetch: nothing can fail or stall mid-interview, and every candidate gets a well-prepared article."""
    global _saved_articles
    if not _saved_articles:
        _saved_articles = getEnrichTool().loadFallbackCurrentAffairs()
        try:
            ingest.ingestSharedCurrentAffairs(_saved_articles)
        except Exception as e:
            logger.error(f"Saved CA ingest failed (CA retrieval may be degraded): {e}")
    return list(_saved_articles)


async def lifespan(app: FastAPI):
    if initLangfuse():
        logger.info("Langfuse tracing enabled")
    try:
        ingest.ingestSharedSyllabus(SYLLABUS_PATH)
    except Exception as e:
        logger.error(f"Syllabus ingest failed (RAG may be degraded): {e}")
    logger.info(f"Saved current-affairs articles for the interview: {len(loadSavedArticles())}")
    yield
    flushLangfuse()
    await session_store.close()


app = FastAPI(title="UPSC Mock Interview Agent", lifespan=lifespan)
app.middleware("http")(limitRequests)
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


def buildStartInterviewResponse(
    session_id: str,
    state: dict,
    enriched: list,
    question_audio: bytes,
) -> StartInterviewResponse:
    ca_briefing = serializeCaBriefing(state.get("last_ca_briefing"))
    return StartInterviewResponse(
        session_id=session_id,
        question=state.get("current_question", ""),
        audio_base64=base64.b64encode(question_audio).decode() if question_audio else "",
        current_phase=state.get("current_phase", "daf_opening"),
        articles_indexed=len(enriched),
        interview_mode=state.get("interview_mode", "full"),
        router_action=state.get("router_action", "pivot"),
        daf_focus=state.get("current_focus_anchor", ""),
        retrieved_chunks=serializeChunks(state.get("last_retrieved_chunks", [])),
        ca_source=serializeCaSource(state.get("last_ca_source")),
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


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/upload-daf", response_model=UploadDAFResponse)
async def uploadDaf(
    file: UploadFile = File(...),
    interview_mode: str = Form(DEFAULT_INTERVIEW_MODE),
):
    getGraph()
    mode_config = resolveInterviewMode(interview_mode)
    session_id = str(uuid.uuid4())
    dest = UPLOAD_DIR / f"{session_id}.pdf"
    content = await file.read()
    dest.write_bytes(content)
    try:
        daf_text = daf_tool.extractTextFromPdf(dest)
        with observationContext("daf_extraction", session_id, as_type="chain"):
            profile = daf_tool.extractDafFields(dest, raw_text=daf_text, session_id=session_id)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        logger.warning(f"DAF upload failed: {exc}")  # details stay in the log; never show server paths to users
        raise HTTPException(
            status_code=400,
            detail="We couldn't read this PDF. Please upload the DAF PDF from the UPSC website (not a scan or photo).",
        ) from exc
    # A DAF holds the candidate's address, parents and roll number: keep only what the interview needs (the
    # profile and the text, in the session), never the file itself.
    dest.unlink(missing_ok=True)
    if not looksLikeDaf(profile):
        raise HTTPException(
            status_code=400,
            detail="This doesn't look like a UPSC DAF (no hometown, education or hobbies found). Please upload your DAF PDF.",
        )
    state = initialState(session_id, daf_text, profile, mode_config)
    state["ca_articles"] = loadSavedArticles()
    await session_store.saveState(session_id, dict(state))
    flushLangfuse()
    return UploadDAFResponse(session_id=session_id, daf_profile=profile)


@app.post("/start-interview", response_model=StartInterviewResponse)
async def startInterview(session_id: str = Form(...)):
    state = await session_store.loadState(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found. Upload a DAF first.")

    enriched = state.get("ca_articles") or []
    if state.get("interview_started") and state.get("current_question"):
        logger.info(f"Interview already started for {session_id[:8]} — returning cached first question")
        cached_q_audio = state.get("start_audio_base64") or ""
        return buildStartInterviewResponse(
            session_id,
            state,
            enriched,
            base64.b64decode(cached_q_audio) if cached_q_audio else b"",
        )

    profile = state["daf_profile"]
    ingest.ingestSharedSyllabus(SYLLABUS_PATH)

    enriched = state.get("ca_articles") or loadSavedArticles()
    state["ca_articles"] = enriched

    article_pool = enriched or state.get("ca_articles") or []
    if article_pool:
        if state.get("interview_started"):
            state["ca_article_cursor"] = (state.get("ca_article_cursor", 0) + 1) % len(article_pool)
        else:
            state["ca_article_cursor"] = random.randint(0, len(article_pool) - 1)
    else:
        state["ca_article_cursor"] = 0

    closing_angles = buildClosingAngles(profile)
    if state.get("interview_started"):
        state["closing_angle_index"] = (state.get("closing_angle_index", 0) + 1) % len(closing_angles)
    else:
        state["closing_angle_index"] = random.randint(0, len(closing_angles) - 1)

    with trackStep(session_id, "first_question"):
        with observationContext("interview_first_question", session_id, as_type="chain"):
            graph = getGraph()
            result = await graph.runFirstQuestion(state)
    state.update(result)
    audio_out = b""
    with trackStep(session_id, "tts"):
        try:
            with observationContext("tts_synthesize", session_id, as_type="tool", input={"chars": len(voiceForTts(state))}):
                audio_out = await tts_tool.synthesize(
                    voiceForTts(state), language_code=INTERVIEW_TTS_LANGUAGE
                )
        except Exception:
            audio_out = b""
    state["interview_started"] = True
    state["start_audio_base64"] = base64.b64encode(audio_out).decode() if audio_out else ""
    recordTurn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.saveState(session_id, state)
    flushLangfuse()
    return buildStartInterviewResponse(session_id, state, enriched, audio_out)


@app.post("/respond", response_model=RespondResponse)
async def respond(session_id: str = Form(...), audio: UploadFile = File(None), text_answer: str = Form(None)):
    state = await session_store.loadState(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.get("interview_complete") and state.get("feedback_report"):
        # A late or double-submitted answer must never re-run the board or change a finished report.
        raise HTTPException(status_code=409, detail="Interview already complete. Open the feedback report.")
    if text_answer:
        transcript = text_answer
    elif audio:
        with trackStep(session_id, "stt"):
            audio_bytes = await audio.read()
            with observationContext("stt_transcribe", session_id, as_type="tool", input={"bytes": len(audio_bytes)}):
                transcript = await transcribeAnswer(audio_bytes, audio.content_type or "audio/wav")
    else:
        raise HTTPException(status_code=400, detail="Provide audio or text_answer")
    state["last_answer"] = transcript
    graph = getGraph()
    with trackStep(session_id, "llm_turn"):
        with observationContext("interview_turn", session_id, as_type="chain", input={"transcript_len": len(transcript)}):
            result = await graph.runTurn(state)
    state.update(result)
    interview_complete = bool(state.get("interview_complete"))
    question = "" if interview_complete else state.get("current_question", "")
    audio_out = b""
    if question:
        with trackStep(session_id, "tts"):
            try:
                with observationContext("tts_synthesize", session_id, as_type="tool", input={"chars": len(voiceForTts(state))}):
                    audio_out = await tts_tool.synthesize(
                    voiceForTts(state), language_code=INTERVIEW_TTS_LANGUAGE
                )
            except Exception:
                audio_out = b""
    recordTurn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.saveState(session_id, state)
    flushLangfuse()
    evaluation = state.get("last_evaluation")
    notes = evaluation.notes if hasattr(evaluation, "notes") else ""
    eval_payload = serializeEvaluation(evaluation)
    ca_briefing = serializeCaBriefing(state.get("last_ca_briefing"))
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
        daf_flags=serializeDafFlags(state.get("daf_flags", [])),
        daf_focus=state.get("current_focus_anchor", ""),
        retrieved_chunks=serializeChunks(state.get("last_retrieved_chunks", [])),
        ca_source=serializeCaSource(state.get("last_ca_source")),
        ca_briefing=ca_briefing,
    )


@app.post("/respond-stream")
async def respondStream(
    session_id: str = Form(...),
    audio: UploadFile = File(None),
    text_answer: str = Form(None),
):
    """Server-Sent Events: metadata after the turn, then TTS chunks as each sentence is synthesized."""
    from fastapi.responses import StreamingResponse
    import json

    state = await session_store.loadState(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    if state.get("interview_complete") and state.get("feedback_report"):
        # A late or double-submitted answer must never re-run the board or change a finished report.
        raise HTTPException(status_code=409, detail="Interview already complete. Open the feedback report.")

    if text_answer:
        transcript = text_answer
    elif audio:
        with trackStep(session_id, "stt"):
            audio_bytes = await audio.read()
            with observationContext("stt_transcribe", session_id, as_type="tool", input={"bytes": len(audio_bytes)}):
                transcript = await transcribeAnswer(audio_bytes, audio.content_type or "audio/wav")
    else:
        raise HTTPException(status_code=400, detail="Provide audio or text_answer")

    state["last_answer"] = transcript
    graph = getGraph()
    with trackStep(session_id, "llm_turn"):
        with observationContext("interview_turn", session_id, as_type="chain", input={"transcript_len": len(transcript)}):
            result = await graph.runTurn(state)
    state.update(result)
    interview_complete = bool(state.get("interview_complete"))
    question = "" if interview_complete else state.get("current_question", "")
    recordTurn(session_id, state.get("current_phase", "daf_opening"))
    await session_store.saveState(session_id, state)
    flushLangfuse()

    voice_text = "" if interview_complete else voiceForTts(state)
    evaluation = state.get("last_evaluation")
    notes = evaluation.notes if hasattr(evaluation, "notes") else ""
    eval_payload = serializeEvaluation(evaluation)
    ca_briefing = serializeCaBriefing(state.get("last_ca_briefing"))

    async def eventGenerator():
        meta = {
            "type": "metadata",
            "session_id": session_id,
            "transcript": transcript,
            "question": question,
            "current_phase": state.get("current_phase"),
            "interview_complete": interview_complete,
            "router_action": state.get("router_action", "pivot"),
            "daf_flags": serializeDafFlags(state.get("daf_flags", [])),
            "daf_focus": state.get("current_focus_anchor", ""),
            "retrieved_chunks": serializeChunks(state.get("last_retrieved_chunks", [])),
            "ca_source": serializeCaSource(state.get("last_ca_source")),
            "ca_briefing": ca_briefing.model_dump() if ca_briefing else None,
            "evaluation_notes": notes,
            "evaluation": eval_payload,
        }
        yield f"data: {json.dumps(meta, default=str)}\n\n"

        wav_parts: list[bytes] = []
        if voice_text:
            with trackStep(session_id, "tts_stream"):
                async for chunk in tts_tool.synthesizeStream(voice_text, language_code=INTERVIEW_TTS_LANGUAGE):
                    chunk_bytes = base64.b64decode(chunk["audio_base64"])
                    wav_parts.append(chunk_bytes)
                    event_data = {"type": "audio_chunk", **chunk}
                    yield f"data: {json.dumps(event_data)}\n\n"
                if wav_parts:
                    combined = concatWav(wav_parts)
                    yield f"data: {json.dumps({'type': 'question_audio', 'audio_base64': base64.b64encode(combined).decode()})}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        eventGenerator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/feedback-report/{session_id}")
async def feedbackReport(session_id: str):
    state = await session_store.loadState(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    report = state.get("feedback_report")
    if not report:
        raise HTTPException(status_code=400, detail="Interview not complete yet")
    return {
        "session_id": session_id,
        "report": report,
        "daf_flags": serializeDafFlags(state.get("daf_flags", [])),
        "interview_mode": state.get("interview_mode", "full"),
    }


@app.get("/metrics/{session_id}")
async def metrics(session_id: str):
    return getMetrics(session_id)
