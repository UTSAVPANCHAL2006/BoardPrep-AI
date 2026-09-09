import asyncio
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.groq_guard import groq_error_is_rate_limit, groq_is_cooling, groq_mark_limited
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import llm_message_text, parse_json_response
from app.config.ca_languages import DEFAULT_CA_VOICE_LANG, CaVoiceLanguage, resolve_ca_language
from app.config.config import CA_USE_LLM_BRIEFING
from app.prompts.ca_briefing_prompt import build_ca_briefing_prompts
from app.schema.interview import EnrichedArticle

logger = get_logger(__name__)

_LLM_TIMEOUT_SEC = 90.0
_MAX_BRIEFING_ATTEMPTS = 2


def clip_text(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0]


def has_latin(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def has_script(text: str, start: int, end: int) -> bool:
    return any(start <= ord(ch) <= end for ch in text or "")


def has_indic(text: str) -> bool:
    return any(0x0900 <= ord(ch) <= 0x0D7F for ch in text or "")


_LATIN_TO_DEVANAGARI = {
    "UPSC": "यूपीएससी",
    "RBI": "आरबीआई",
    "GST": "जीएसटी",
    "UN": "यूएन",
    "SCO": "एससीओ",
    "GS": "जीएस",
    "GS1": "जीएस वन",
    "GS2": "जीएस टू",
    "GS3": "जीएस थ्री",
    "GS4": "जीएस फोर",
    "Prelims": "प्रीलिम्स",
    "Mains": "मेन्स",
    "NEET": "नीट",
    "FIR": "एफआईआर",
    "GDP": "जीडीपी",
    "IMF": "आईएमएफ",
    "WHO": "डब्ल्यूएचओ",
    "AI": "एआई",
}


def repair_voice_script(text: str, lang: CaVoiceLanguage) -> str:
    """Fix common LLM slips: Roman acronyms → Devanagari; drop stray English tokens."""
    if lang.allow_latin or not text:
        return text
    out = text
    for eng, dev in _LATIN_TO_DEVANAGARI.items():
        out = re.sub(rf"\b{re.escape(eng)}\b", dev, out, flags=re.IGNORECASE)
    if has_latin(out):
        out = re.sub(r"[A-Za-z]+", " ", out)
        out = re.sub(r"\s+", " ", out).strip()
    return out


def voice_is_valid(text: str, lang: CaVoiceLanguage) -> bool:
    voice = (text or "").strip()
    min_len = 50 if lang.code != "en" else 80
    if len(voice) < min_len:
        return False
    if lang.allow_latin:
        return bool(re.search(r"[A-Za-z]{12,}", voice)) and not has_indic(voice)
    if has_latin(voice):
        return False
    if lang.script_start is None or lang.script_end is None:
        return False
    return has_script(voice, lang.script_start, lang.script_end)


def extract_briefing_voice(raw: str) -> str:
    match = re.search(r'"briefing_voice"\s*:\s*"([\s\S]*?)"\s*,\s*"prelims_pointer"', raw or "")
    if not match:
        match = re.search(r'"briefing_voice"\s*:\s*"([\s\S]*?)"\s*}', raw or "")
    if not match:
        return ""
    return match.group(1).replace("\\n", " ").replace('\\"', '"').strip()


class CaBriefingTool:
    """Teacher-style voice notes. Screen fields stay English; voice follows selected language."""

    def __init__(self, llm=None):
        self.llm = llm

    def fallback_briefing(self, article: EnrichedArticle, lang: CaVoiceLanguage) -> dict:
        gs_tags = [t for t in article.gs_tags if t.lower() != "prelims"]
        gs = gs_tags[0] if gs_tags else "General Studies"
        highlights = article.key_highlights or []
        fact = highlights[0] if highlights else article.title
        prelims_fact = highlights[1] if len(highlights) > 1 else fact
        mains = clip_text(article.detailed_insights or (highlights[2] if len(highlights) > 2 else ""), 160)
        return {
            "briefing_text": clip_text(article.detailed_insights or fact, 280),
            "briefing_voice": lang.fallback_voice,
            "is_fallback": True,
            "voice_language": lang.code,
            "prelims_pointer": clip_text(prelims_fact, 140),
            "mains_angle": mains or "Link the event to India's policy interest and regional context.",
            "gs_link": ", ".join(gs_tags[:2]) or gs,
            "interview_tip": "State the fact, then explain why it matters for India.",
            "article_title": article.title,
            "gs_tags": article.gs_tags,
            "key_highlights": article.key_highlights,
            "key_concepts": article.key_concepts,
        }

    def teacher_briefing_from_article(self, article: EnrichedArticle, lang: CaVoiceLanguage) -> dict:
        """Article-specific voice script when LLM is unavailable — uses enriched notes, not generic filler."""
        highlights = [h.strip() for h in (article.key_highlights or []) if h and h.strip()]
        concepts = article.key_concepts or {}
        gs_tags = [t for t in (article.gs_tags or []) if t.lower() != "prelims"]
        gs_link = ", ".join(gs_tags[:2]) or "General Studies"
        prelims = highlights[1] if len(highlights) > 1 else (highlights[0] if highlights else article.title)
        mains = clip_text(
            article.detailed_insights or (highlights[2] if len(highlights) > 2 else ""),
            180,
        )
        interview_tip = "State the fact, then explain why it matters for India."
        briefing_text = clip_text(article.detailed_insights or (highlights[0] if highlights else article.title), 280)

        if lang.code == "hi":
            parts = ["नमस्कार, आज की महत्वपूर्ण खबर पर बात करते हैं।"]
            if article.source:
                parts.append(f"यह {article.source} की रिपोर्ट है।")
            if highlights:
                parts.append("मुख्य बातें सुनिए।")
                ordinals = ("पहली", "दूसरी", "तीसरी", "चौथी")
                for i, point in enumerate(highlights[:4]):
                    label = ordinals[i] if i < len(ordinals) else "अगली"
                    parts.append(f"{label} बात — {point}.")
            elif article.detailed_insights:
                parts.append(clip_text(article.detailed_insights, 320))
            for name, meaning in list(concepts.items())[:2]:
                parts.append(f"{name} — {meaning}.")
            parts.append(f"यूपीएससी में इसे {gs_link} के तहत रखें।")
            parts.append(
                "प्रीलिम्स में तथ्य याद रखें, मेन्स में भारत पर असर लिखें, "
                "और इंटरव्यू में अपनी राय साफ़ रखें।"
            )
            voice = " ".join(parts)
            for eng, dev in _LATIN_TO_DEVANAGARI.items():
                voice = re.sub(rf"\b{re.escape(eng)}\b", dev, voice, flags=re.IGNORECASE)
        elif lang.allow_latin:
            parts = ["Let's walk through today's important story."]
            if article.source:
                parts.append(f"This report is from {article.source}.")
            if highlights:
                parts.append("Key points:")
                for point in highlights[:4]:
                    parts.append(point + ".")
            elif article.detailed_insights:
                parts.append(clip_text(article.detailed_insights, 320))
            for name, meaning in list(concepts.items())[:2]:
                parts.append(f"{name}: {meaning}.")
            parts.append(f"Place this under {gs_link} for UPSC.")
            parts.append("Remember facts for Prelims, India's angle for Mains, and a clear view for Interview.")
            voice = " ".join(parts)
        else:
            base = self.fallback_briefing(article, lang)
            base["is_fallback"] = False
            base["briefing_voice"] = clip_text(
                " ".join(highlights[:3]) or article.detailed_insights or article.title,
                900,
            )
            return base

        if len(voice.strip()) < 80:
            return self.fallback_briefing(article, lang)

        return {
            "briefing_text": briefing_text,
            "briefing_voice": clip_text(voice, 1200),
            "is_fallback": False,
            "voice_language": lang.code,
            "prelims_pointer": clip_text(prelims, 140),
            "mains_angle": mains or "Link the event to India's policy interest and regional context.",
            "gs_link": gs_link,
            "interview_tip": interview_tip,
            "article_title": article.title,
            "gs_tags": article.gs_tags,
            "key_highlights": article.key_highlights,
            "key_concepts": article.key_concepts,
        }

    def merge_llm(self, article: EnrichedArticle, data: dict, lang: CaVoiceLanguage) -> dict:
        base = self.fallback_briefing(article, lang)
        voice = repair_voice_script((data.get("briefing_voice") or "").strip(), lang)
        if voice_is_valid(voice, lang):
            base["briefing_voice"] = voice
            base["is_fallback"] = False
        if data.get("briefing_text"):
            base["briefing_text"] = clip_text(str(data["briefing_text"]), 280)
        if data.get("prelims_pointer"):
            base["prelims_pointer"] = clip_text(str(data["prelims_pointer"]), 160)
        if data.get("mains_angle"):
            base["mains_angle"] = clip_text(str(data["mains_angle"]), 180)
        if data.get("gs_link"):
            base["gs_link"] = str(data["gs_link"]).strip()
        if data.get("interview_tip"):
            base["interview_tip"] = clip_text(str(data["interview_tip"]), 140)
        return base

    def parse_briefing_payload(self, raw: str) -> dict:
        try:
            return parse_json_response(raw)
        except Exception as e:
            voice = extract_briefing_voice(raw)
            if voice:
                logger.warning("CaBriefingTool JSON broken, recovered briefing_voice")
                return {"briefing_voice": voice}
            logger.warning(f"CaBriefingTool raw LLM preview: {raw[:400]!r}")
            raise e

    def retry_extra(self, lang: CaVoiceLanguage) -> str:
        if lang.code == "hi":
            return "पिछला जवाब गलत था। सिर्फ JSON दो। briefing_voice में एक भी English letter नहीं। पहली लिखावट { हो।"
        if lang.code == "en":
            return "Previous answer was wrong. JSON only. briefing_voice must be spoken English with no Indic script. First character {."
        return (
            f"Previous answer was wrong. JSON only. briefing_voice must be spoken {lang.name} "
            f"in {lang.script} with no English letters. First character {{."
        )

    async def invoke_briefing(self, system: str, user: str, session_id: str, extra: str = "") -> dict:
        from app.observability.langfuse_client import langchain_invoke_config

        llm = self.llm.get_llm(temperature=0.2)
        config = langchain_invoke_config(
            session_id,
            run_name="ca_briefing_voice",
            tags=["upsc-interview", "current-affairs", "voice"],
        )
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=user if not extra else f"{user}\n\n{extra}"),
        ]
        response = await asyncio.wait_for(llm.ainvoke(messages, config=config), timeout=_LLM_TIMEOUT_SEC)
        raw = llm_message_text(response)
        if not raw.strip():
            logger.warning(f"CaBriefingTool empty LLM text; content_type={type(getattr(response, 'content', None))}")
        return self.parse_briefing_payload(raw)

    async def generate_briefing(
        self,
        article: EnrichedArticle,
        session_id: str = "",
        language: str = DEFAULT_CA_VOICE_LANG,
        use_llm: bool | None = None,
    ) -> dict:
        lang = resolve_ca_language(language)
        llm_enabled = CA_USE_LLM_BRIEFING if use_llm is None else use_llm
        if not llm_enabled:
            logger.info(f"CaBriefingTool template ({lang.code}): {article.title[:60]}")
            return self.teacher_briefing_from_article(article, lang)

        try:
            logger.info(f"CaBriefingTool started ({lang.code}): {article.title[:60]}")
            if not self.llm:
                return self.teacher_briefing_from_article(article, lang)
            if groq_is_cooling():
                logger.warning(f"CaBriefingTool skipping Groq ({lang.code}) — cooldown, using template voice")
                return self.teacher_briefing_from_article(article, lang)

            highlights = article.key_highlights or []
            concepts = article.key_concepts or {}
            concept_lines = "\n".join(f"{k}: {v}" for k, v in list(concepts.items())[:4]) or "none"
            system, user_template = build_ca_briefing_prompts(lang)
            user = user_template.format(
                title=article.title,
                source=article.source or "",
                gs_tags=", ".join(article.gs_tags) or "General Studies",
                is_prelims_relevant=article.is_prelims_relevant,
                top_highlight="\n".join(f"- {h}" for h in highlights[:4]) or article.title,
                concepts=concept_lines,
                short_insight=clip_text(article.detailed_insights or "", 400),
            )

            data: dict = {}
            last_err: Exception | None = None
            for attempt in range(_MAX_BRIEFING_ATTEMPTS):
                extra = "" if attempt == 0 else self.retry_extra(lang)
                try:
                    data = await self.invoke_briefing(system, user, session_id, extra)
                    voice = repair_voice_script((data.get("briefing_voice") or "").strip(), lang)
                    if voice != (data.get("briefing_voice") or "").strip():
                        data["briefing_voice"] = voice
                    if voice_is_valid(voice, lang):
                        break
                    last_err = ValueError("briefing_voice failed script/language checks")
                    logger.warning(
                        f"CaBriefingTool voice rejected ({lang.code}), attempt {attempt + 1}; "
                        f"preview={voice[:120]!r}"
                    )
                    if data.get("briefing_text") or data.get("prelims_pointer"):
                        result = self.merge_llm(article, data, lang)
                        logger.info(f"CaBriefingTool using LLM notes + fallback voice ({lang.code})")
                        return result
                    continue
                except asyncio.TimeoutError:
                    logger.warning(f"CaBriefingTool LLM timed out after {_LLM_TIMEOUT_SEC}s ({lang.code})")
                    return self.teacher_briefing_from_article(article, lang)
                except Exception as e:
                    last_err = e
                    if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
                        logger.warning(f"CaBriefingTool LLM timed out ({lang.code})")
                        return self.teacher_briefing_from_article(article, lang)
                    if groq_error_is_rate_limit(e):
                        groq_mark_limited(e)
                        logger.warning("CaBriefingTool Groq rate limit — using template voice")
                        return self.teacher_briefing_from_article(article, lang)
                    if "model_not_found" in str(e).lower() or "404" in str(e):
                        logger.error(f"CaBriefingTool Groq model missing: {e}")
                        return self.teacher_briefing_from_article(article, lang)
                    err_label = type(e).__name__
                    err_msg = str(e).strip() or "no message"
                    logger.warning(f"CaBriefingTool invoke failed [{err_label}]: {err_msg}, retry {attempt + 1}")
                    continue
            else:
                if last_err:
                    logger.warning(f"CaBriefingTool giving {lang.code} template after retries: {last_err}")
                return self.teacher_briefing_from_article(article, lang)

            result = self.merge_llm(article, data, lang)
            logger.info(
                f"CaBriefingTool completed ({lang.code}, {len(result['briefing_voice'])} chars, "
                f"latin={has_latin(result['briefing_voice'])})"
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("CaBriefingTool LLM timed out, using template voice")
            return self.teacher_briefing_from_article(article, lang)
        except Exception as e:
            if groq_error_is_rate_limit(e):
                groq_mark_limited(e)
            logger.warning(f"CaBriefingTool LLM failed ({e}), using template voice")
            try:
                return self.teacher_briefing_from_article(article, lang)
            except Exception as inner:
                logger.error(f"Error in CaBriefingTool: {inner}")
                raise CustomException("CaBriefingTool Failed", inner)
