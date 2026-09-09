import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=True)


def get_sarvam_api_key() -> str:
    """Read Sarvam key from .env (reloads so key updates without full server restart)."""
    load_dotenv(BASE_DIR / ".env", override=True)
    return os.getenv("SARVAM_API_KEY", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GROQ_API_KEY = OPENAI_API_KEY
GROQ_MODEL = OPENAI_MODEL
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60)))  # 1 hour default
CA_BUNDLE_TTL_SECONDS = int(os.getenv("CA_BUNDLE_TTL_SECONDS", str(24 * 60 * 60)))  # 24 hours
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

INTERVIEW_MODES = {
    "quick": {"max_questions": 4, "exchanges_per_phase": 1},
    "full": {"max_questions": 12, "exchanges_per_phase": 3},
}
DEFAULT_INTERVIEW_MODE = os.getenv("INTERVIEW_MODE", "full")

LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

CHROMA_DIR = BASE_DIR / CHROMA_PATH if not Path(CHROMA_PATH).is_absolute() else Path(CHROMA_PATH)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SYLLABUS_PATH = BASE_DIR / "app" / "data" / "sample_syllabus.txt"
FALLBACK_CA_PATH = BASE_DIR / "app" / "data" / "fallback_current_affairs.json"
DAILY_CA_ARTICLE_COUNT = int(os.getenv("DAILY_CA_ARTICLE_COUNT", "10"))
# Set false only for emergency demos when LLM quota is exhausted.
CA_USE_LLM_BRIEFING = os.getenv("CA_USE_LLM_BRIEFING", "true").lower() in ("1", "true", "yes")
# Listen click: use Redis cache instantly; if miss, fast template+TTS (not 90s LLM). Prewarm still uses LLM.
CA_EXPLAIN_LLM_ON_DEMAND = os.getenv("CA_EXPLAIN_LLM_ON_DEMAND", "false").lower() in ("1", "true", "yes")
CA_MIDNIGHT_PREWARM_ENABLED = os.getenv("CA_MIDNIGHT_PREWARM_ENABLED", "true").lower() in ("1", "true", "yes")
RAG_VECTORS_ENABLED = os.getenv("RAG_VECTORS_ENABLED", "true").lower() in ("1", "true", "yes")
