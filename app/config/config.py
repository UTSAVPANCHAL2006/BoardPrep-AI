"""All settings, read from the .env file in one place."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


def getSarvamApiKey() -> str:
    """Read Sarvam key from .env (reloads so key updates without full server restart)."""
    load_dotenv(BASE_DIR / ".env", override=True)
    return os.getenv("SARVAM_API_KEY", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# Non-reasoning model for JSON LLM calls (CA voice, interview questions, eval)
CA_BRIEFING_MODEL = os.getenv("CA_BRIEFING_MODEL", "gpt-4o-mini")
INTERVIEW_JSON_MODEL = os.getenv("INTERVIEW_JSON_MODEL", CA_BRIEFING_MODEL)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60)))  # 1 hour default
CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
HF_EMBEDDING_MODEL = os.getenv("HF_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "hi-IN")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "aayan")
SARVAM_TTS_PACE = float(os.getenv("SARVAM_TTS_PACE", "1.05"))
CA_BRIEFING_WORDS_MIN = int(os.getenv("CA_BRIEFING_WORDS_MIN", "150"))
CA_BRIEFING_WORDS_MAX = int(os.getenv("CA_BRIEFING_WORDS_MAX", "175"))
CA_BRIEFING_VOICE_MAX_CHARS = int(os.getenv("CA_BRIEFING_VOICE_MAX_CHARS", "1050"))
SARVAM_TTS_TEMPERATURE = float(os.getenv("SARVAM_TTS_TEMPERATURE", "0.65"))
SARVAM_STT_MODE = os.getenv("SARVAM_STT_MODE", "codemix")
INTERVIEW_TTS_LANGUAGE = os.getenv("INTERVIEW_TTS_LANGUAGE", "hi-IN")

INTERVIEW_MODES = {
    "quick": {
        "max_questions": 5,
        "exchanges_per_phase": 1,
        "phase_exchanges": {"daf_opening": 2},
    },
    "full": {"max_questions": 12, "exchanges_per_phase": 3},
}
DEFAULT_INTERVIEW_MODE = os.getenv("INTERVIEW_MODE", "full")


CHROMA_DIR = BASE_DIR / CHROMA_PATH if not Path(CHROMA_PATH).is_absolute() else Path(CHROMA_PATH)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SYLLABUS_PATH = BASE_DIR / "app" / "data" / "sample_syllabus.txt"
FALLBACK_CA_PATH = BASE_DIR / "app" / "data" / "fallback_current_affairs.json"
# Set false only for emergency demos when LLM quota is exhausted.
CA_USE_LLM_BRIEFING = os.getenv("CA_USE_LLM_BRIEFING", "true").lower() in ("1", "true", "yes")
# Listen click: use Redis cache instantly; if miss, fast template+TTS (not 90s LLM). Prewarm still uses LLM.
# Fetch today's news into Redis (Upstash) when bundle missing/stale — NOT at midnight.
# 11-language voice prewarm batch — keep false on Upstash free tier (Redis fills fast).
RAG_VECTORS_ENABLED = os.getenv("RAG_VECTORS_ENABLED", "true").lower() in ("1", "true", "yes")
