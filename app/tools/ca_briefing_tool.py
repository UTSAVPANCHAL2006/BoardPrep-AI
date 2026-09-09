import asyncio
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.groq_guard import groq_error_is_rate_limit, groq_is_cooling, groq_mark_limited
from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import llm_message_text, parse_json_response
from app.config.ca_languages import DEFAULT_CA_VOICE_LANG, CaVoiceLanguage, resolve_ca_language
from app.config.config import CA_BRIEFING_VOICE_MAX_CHARS, CA_BRIEFING_WORDS_MAX, CA_BRIEFING_WORDS_MIN, CA_USE_LLM_BRIEFING
from app.prompts.ca_briefing_prompt import build_ca_briefing_prompts
from app.schema.interview import EnrichedArticle

logger = get_logger(__name__)

_LLM_TIMEOUT_SEC = 90.0
_SIMPLE_NATIVE_TIMEOUT_SEC = 55.0
_MAX_BRIEFING_ATTEMPTS = 2

_SIMPLE_NATIVE_SYSTEM = """You write UPSC Current Affairs classroom voice scripts for Indian students.
Return JSON only with one key: briefing_voice.

Write briefing_voice entirely in {language_name} ({native_name}) using the {script} script.
No English letters (a-z, A-Z) inside briefing_voice.
Use natural spoken {language_name}, about {word_band} words: hook question, background, all important facts,
impact on India, UPSC exam link, one-line recap.
Do not read the English headline word-for-word — explain the story in {language_name}."""

_SIMPLE_NATIVE_USER = """Source: {source}
GS papers: {gs_tags}
Prelims relevant: {is_prelims_relevant}

Facts (understand and teach in {language_name}; do not copy English phrases aloud):
{top_highlight}

Terms:
{concepts}

Why it matters:
{short_insight}

Return JSON only: {{"briefing_voice": "..."}}"""


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

# Native classroom framing per language (article facts may stay English — Sarvam codemix handles TTS).
_TEACHER_VOICE_FRAMES: dict[str, dict] = {
    "bn": {
        "intro": "নমস্কার, আজকের গুরুত্বপূর্ণ খবর নিয়ে কথা বলি।",
        "source": "এটি {source} এর রিপোর্ট।",
        "highlights_intro": "মূল বিষয়গুলো শুনুন।",
        "ordinals": ("প্রথম", "দ্বিতীয়", "তৃতীয়", "চতুর্থ"),
        "gs": "ইউপিএসসিতে এটিকে {gs_link} এর অধীনে রাখুন।",
        "close": "প্রিলিমসে তথ্য মনে রাখুন, মেনসে ভারতের প্রভাব লিখুন, ইন্টারভিউতে স্পষ্ট মতামত রাখুন।",
    },
    "ta": {
        "intro": "வணக்கம், இன்றைய முக்கிய செய்தியைப் பார்ப்போம்.",
        "source": "இது {source} இலிருந்து வந்த அறிக்கை.",
        "highlights_intro": "முக்கிய புள்ளிகளைக் கேளுங்கள்.",
        "ordinals": ("முதல்", "இரண்டாவது", "மூன்றாவது", "நான்காவது"),
        "gs": "இதை யுபிஎஸ்சியில் {gs_link} கீழ் வையுங்கள்.",
        "close": "ப்ரிலிம்ஸில் உண்மைகளை நினைவில் வையுங்கள், மெயின்ஸில் இந்தியாவின் தாக்கத்தை எழுதுங்கள்.",
    },
    "te": {
        "intro": "నమస్కారం, ఈరోజు ముఖ్యమైన వార్త గురించి మాట్లాడుదాం.",
        "source": "ఇది {source} నుండి వచ్చిన నివేదిక.",
        "highlights_intro": "ముఖ్య అంశాలు వినండి.",
        "ordinals": ("మొదటి", "రెండవ", "మూడవ", "నాల్గవ"),
        "gs": "దీన్ని యుపిఎస్సీలో {gs_link} కింద ఉంచండి.",
        "close": "ప్రిలిమ్స్‌లో వాస్తవాలు గుర్తుంచుకోండి, మెయిన్స్‌లో భారతదేశంపై ప్రభావం రాయండి.",
    },
    "mr": {
        "intro": "नमस्कार, आजच्या महत्त्वाच्या बातमीवर बोलूया.",
        "source": "ही {source} ची बातमी आहे.",
        "highlights_intro": "मुख्य मुद्दे ऐका.",
        "ordinals": ("पहिला", "दुसरा", "तिसरा", "चौथा"),
        "gs": "यूपीएससीमध्ये हे {gs_link} अंतर्गत ठेवा.",
        "close": "प्रिलिम्समध्ये तथ्ये लक्षात ठेवा, मेन्समध्ये भारतावर परिणाम लिहा.",
    },
    "kn": {
        "intro": "ನಮಸ್ಕಾರ, ಇಂದಿನ ಪ್ರಮುಖ ಸುದ್ದಿಯ ಬಗ್ಗೆ ಮಾತನಾಡೋಣ.",
        "source": "ಇದು {source} ನಿಂದ ಬಂದ ವರದಿ.",
        "highlights_intro": "ಮುಖ್ಯ ಅಂಶಗಳನ್ನು ಕೇಳಿ.",
        "ordinals": ("ಮೊದಲ", "ಎರಡನೇ", "ಮೂರನೇ", "ನಾಲ್ಕನೇ"),
        "gs": "ಯುಪಿಎಸ್ಸಿಯಲ್ಲಿ ಇದನ್ನು {gs_link} ಅಡಿಯಲ್ಲಿ ಇರಿಸಿ.",
        "close": "ಪ್ರಿಲಿಮ್ಸ್‌ನಲ್ಲಿ ವಾಸ್ತವಗಳನ್ನು ನೆನಪಿಟ್ಟುಕೊಳ್ಳಿ, ಮೇನ್ಸ್‌ನಲ್ಲಿ ಭಾರತದ ಮೇಲೆ ಪರಿಣಾಮ ಬರೆಯಿರಿ.",
    },
    "gu": {
        "intro": "નમસ્કાર, આજની મહત્વપૂર્ણ ખબર વિશે વાત કરીએ.",
        "source": "આ {source} ની રિપોર્ટ છે.",
        "highlights_intro": "મુખ્ય બાબતો સાંભળો.",
        "ordinals": ("પહેલી", "બીજી", "ત્રીજી", "ચોથી"),
        "gs": "યુપીએસસીમાં આને {gs_link} હેઠળ રાખો.",
        "close": "પ્રિલિમ્સમાં તથ્ય યાદ રાખો, મેન્સમાં ભારત પર અસર લખો, ઇન્ટરવ્યૂમાં સ્પષ્ટ અભિપ્રાય રાખો.",
    },
    "ml": {
        "intro": "നമസ്കാരം, ഇന്നത്തെ പ്രധാന വാർത്ത നോക്കാം.",
        "source": "ഇത് {source} ൽ നിന്നുള്ള റിപ്പോർട്ടാണ്.",
        "highlights_intro": "പ്രധാന കാര്യങ്ങൾ കേൾക്കൂ.",
        "ordinals": ("ഒന്നാം", "രണ്ടാം", "മൂന്നാം", "നാലാം"),
        "gs": "ഇത് യുപിഎസ്സിയിൽ {gs_link} കീഴിൽ വയ്ക്കുക.",
        "close": "പ്രിലിമ്സിൽ വസ്തുതകൾ ഓർമ്മിക്കുക, മെയിൻസിൽ ഇന്ത്യയിലെ സ്വാധീനം എഴുതുക.",
    },
    "pa": {
        "intro": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਅੱਜ ਦੀ ਮਹੱਤਵਪੂਰਨ ਖ਼ਬਰ ਬਾਰੇ ਗੱਲ ਕਰੀਏ.",
        "source": "ਇਹ {source} ਦੀ ਰਿਪੋਰਟ ਹੈ.",
        "highlights_intro": "ਮੁੱਖ ਗੱਲਾਂ ਸੁਣੋ.",
        "ordinals": ("ਪਹਿਲੀ", "ਦੂਜੀ", "ਤੀਜੀ", "ਚੌਥੀ"),
        "gs": "ਯੂਪੀਐਸਸੀ ਵਿੱਚ ਇਸਨੂੰ {gs_link} ਹੇਠ ਰੱਖੋ.",
        "close": "ਪ੍ਰੀਲਿਮਸ ਵਿੱਚ ਤੱਥ ਯਾਦ ਰੱਖੋ, ਮੇਨਜ਼ ਵਿੱਚ ਭਾਰਤ ਉੱਤੇ ਅਸਰ ਲਿਖੋ.",
    },
    "od": {
        "intro": "ନମସ୍କାର, ଆଜିର ଗୁରୁତ୍ୱପୂର୍ଣ୍ଣ ଖବର ନେଇ କହିବା.",
        "source": "ଏହା {source} ର ରିପୋର୍ଟ.",
        "highlights_intro": "ମୁଖ୍ୟ ବିଷୟ ଶୁଣ.",
        "ordinals": ("ପ୍ରଥମ", "ଦ୍ଵିତୀୟ", "ତୃତୀୟ", "ଚତୁର୍ଥ"),
        "gs": "ଏହାକୁ ଯୁପିଏସସିରେ {gs_link} ତଳେ ରଖ.",
        "close": "ପ୍ରିଲିମ୍ସରେ ତଥ୍ୟ ମନେରଖ, ମେନ୍ସରେ ଭାରତ ଉପରେ ପ୍ରଭାବ ଲେଖ.",
    },
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

    def _article_voice_english(
        self,
        article: EnrichedArticle,
        highlights: list[str],
        concepts: dict,
        gs_link: str,
    ) -> str:
        """Article facts for Sarvam regional TTS (codemix reads English news content in kn-IN, ta-IN, etc.)."""
        parts = [f"Today's important story: {article.title}."]
        if article.source:
            parts.append(f"This report is from {article.source}.")
        if highlights:
            parts.append("Key points:")
            for point in highlights[:4]:
                parts.append(point + ".")
        elif article.detailed_insights:
            parts.append(clip_text(article.detailed_insights, 400))
        for name, meaning in list(concepts.items())[:2]:
            parts.append(f"{name}: {meaning}.")
        parts.append(f"Place this under {gs_link} for UPSC.")
        parts.append("Remember facts for Prelims, India's angle for Mains, and a clear view for Interview.")
        return " ".join(parts)

    def _article_voice_native(
        self,
        article: EnrichedArticle,
        highlights: list[str],
        concepts: dict,
        gs_link: str,
        lang: CaVoiceLanguage,
    ) -> str:
        frame = _TEACHER_VOICE_FRAMES.get(lang.code)
        if not frame:
            return self._article_voice_english(article, highlights, concepts, gs_link)
        parts = [frame["intro"]]
        if article.source:
            parts.append(frame["source"].format(source=article.source))
        if highlights:
            parts.append(frame["highlights_intro"])
            ordinals = frame["ordinals"]
            for i, point in enumerate(highlights[:4]):
                label = ordinals[i] if i < len(ordinals) else ordinals[-1]
                parts.append(f"{label}.")
        elif article.detailed_insights:
            parts.append(clip_text(article.detailed_insights, 400))
        for name, meaning in list(concepts.items())[:2]:
            parts.append(f"{name} — {meaning}.")
        parts.append(frame["gs"].format(gs_link=gs_link))
        parts.append(frame["close"])
        voice = " ".join(parts)
        if lang.script_start and lang.script_end and lang.script_start <= 0x097F:
            for eng, dev in _LATIN_TO_DEVANAGARI.items():
                voice = re.sub(rf"\b{re.escape(eng)}\b", dev, voice, flags=re.IGNORECASE)
        return voice

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
                parts.append(clip_text(article.detailed_insights, 280))
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
            voice = self._article_voice_english(article, highlights, concepts, gs_link)
        else:
            voice = self._article_voice_native(article, highlights, concepts, gs_link, lang)

        if len(voice.strip()) < 80:
            extra = clip_text(article.detailed_insights or article.title, 400)
            if lang.allow_latin:
                voice = f"{article.title}. {extra}".strip()
            else:
                frame = _TEACHER_VOICE_FRAMES.get(lang.code, {})
                intro = frame.get("intro", "")
                voice = f"{intro} {extra}".strip()
        if len(voice.strip()) < 40:
            return self.fallback_briefing(article, lang)

        return {
            "briefing_text": briefing_text,
            "briefing_voice": clip_text(voice, CA_BRIEFING_VOICE_MAX_CHARS),
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
        voice = repair_voice_script((data.get("briefing_voice") or "").strip(), lang)
        if voice_is_valid(voice, lang):
            base = self.teacher_briefing_from_article(article, lang)
            base["briefing_voice"] = clip_text(voice, CA_BRIEFING_VOICE_MAX_CHARS)
            base["is_fallback"] = False
        else:
            base = self.teacher_briefing_from_article(article, lang)
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

    async def _call_llm_json(
        self,
        system: str,
        user: str,
        session_id: str,
        *,
        run_name: str,
        max_tokens: int = 700,
        timeout: float = _LLM_TIMEOUT_SEC,
    ) -> dict:
        from app.observability.langfuse_client import langchain_invoke_config

        llm = self.llm.get_llm(temperature=0.2, max_tokens=max_tokens)
        try:
            llm = llm.bind(response_format={"type": "json_object"})
        except Exception:
            pass
        config = langchain_invoke_config(
            session_id,
            run_name=run_name,
            tags=["upsc-interview", "current-affairs", "voice"],
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        response = await asyncio.wait_for(llm.ainvoke(messages, config=config), timeout=timeout)
        raw = llm_message_text(response)
        if not raw.strip():
            logger.warning(
                f"CaBriefingTool empty LLM text ({run_name}); "
                f"content_type={type(getattr(response, 'content', None))}"
            )
        return self.parse_briefing_payload(raw)

    async def invoke_simple_native_voice(
        self, article: EnrichedArticle, lang: CaVoiceLanguage, session_id: str
    ) -> dict:
        if lang.code in ("hi", "en") or lang.allow_latin:
            raise ValueError("simple native voice is for Indic regional languages only")
        highlights = article.key_highlights or []
        concepts = article.key_concepts or {}
        concept_lines = "\n".join(f"{k}: {v}" for k, v in list(concepts.items())[:4]) or "none"
        word_band = f"{CA_BRIEFING_WORDS_MIN}–{CA_BRIEFING_WORDS_MAX}"
        system = _SIMPLE_NATIVE_SYSTEM.format(
            language_name=lang.name,
            native_name=lang.native_name,
            script=lang.script,
            word_band=word_band,
        )
        user = _SIMPLE_NATIVE_USER.format(
            source=article.source or "",
            gs_tags=", ".join(article.gs_tags) or "General Studies",
            is_prelims_relevant=article.is_prelims_relevant,
            language_name=lang.name,
            top_highlight="\n".join(f"- {h}" for h in highlights[:4]) or article.title,
            concepts=concept_lines,
            short_insight=clip_text(article.detailed_insights or "", 400),
        )
        return await self._call_llm_json(
            system,
            user,
            session_id,
            run_name=f"ca_briefing_native_{lang.code}",
            max_tokens=700,
            timeout=_SIMPLE_NATIVE_TIMEOUT_SEC,
        )

    async def _finish_regional_voice(
        self,
        article: EnrichedArticle,
        lang: CaVoiceLanguage,
        session_id: str,
        last_err: Exception | None = None,
    ) -> dict:
        if lang.code not in ("hi", "en"):
            try:
                data = await self.invoke_simple_native_voice(article, lang, session_id)
                voice = repair_voice_script((data.get("briefing_voice") or "").strip(), lang)
                if voice != (data.get("briefing_voice") or "").strip():
                    data["briefing_voice"] = voice
                if voice_is_valid(voice, lang):
                    result = self.merge_llm(article, data, lang)
                    logger.info(f"CaBriefingTool native LLM ok ({lang.code}, {len(result['briefing_voice'])} chars)")
                    return result
            except Exception as e:
                logger.warning(f"CaBriefingTool native LLM fallback failed ({lang.code}): {e}")
        if last_err:
            logger.warning(f"CaBriefingTool giving {lang.code} template after retries: {last_err}")
        return self.teacher_briefing_from_article(article, lang)

    async def invoke_briefing(self, system: str, user: str, session_id: str, extra: str = "") -> dict:
        return await self._call_llm_json(
            system,
            user if not extra else f"{user}\n\n{extra}",
            session_id,
            run_name="ca_briefing_voice",
            max_tokens=800,
        )

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

            if session_id == "daily-ca-prewarm":
                max_attempts = 1
            elif lang.code not in ("hi", "en"):
                max_attempts = 1  # full prompt once, then simpler native-LLM fallback
            else:
                max_attempts = _MAX_BRIEFING_ATTEMPTS
            data: dict = {}
            last_err: Exception | None = None
            for attempt in range(max_attempts):
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
                    return await self._finish_regional_voice(article, lang, session_id)
                except Exception as e:
                    last_err = e
                    if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
                        logger.warning(f"CaBriefingTool LLM timed out ({lang.code})")
                        return await self._finish_regional_voice(article, lang, session_id)
                    if groq_error_is_rate_limit(e):
                        groq_mark_limited(e)
                        logger.warning("CaBriefingTool Groq rate limit — using native fallback")
                        return await self._finish_regional_voice(article, lang, session_id)
                    if "model_not_found" in str(e).lower() or "404" in str(e):
                        logger.error(f"CaBriefingTool Groq model missing: {e}")
                        return await self._finish_regional_voice(article, lang, session_id)
                    err_label = type(e).__name__
                    err_msg = str(e).strip() or "no message"
                    logger.warning(f"CaBriefingTool invoke failed [{err_label}]: {err_msg}, retry {attempt + 1}")
                    continue
            else:
                return await self._finish_regional_voice(article, lang, session_id, last_err)

            result = self.merge_llm(article, data, lang)
            logger.info(
                f"CaBriefingTool completed ({lang.code}, {len(result['briefing_voice'])} chars, "
                f"latin={has_latin(result['briefing_voice'])})"
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("CaBriefingTool LLM timed out, using native fallback")
            return await self._finish_regional_voice(article, lang, session_id)
        except Exception as e:
            if groq_error_is_rate_limit(e):
                groq_mark_limited(e)
            logger.warning(f"CaBriefingTool LLM failed ({e}), using native fallback")
            try:
                return await self._finish_regional_voice(article, lang, session_id, e)
            except Exception as inner:
                logger.error(f"Error in CaBriefingTool: {inner}")
                raise CustomException("CaBriefingTool Failed", inner)
