"""Sarvam Bulbul v3 languages used for CA classroom voice.

Coverage matches UPSC-heavy mother tongues in India plus exam English.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CaVoiceLanguage:
    code: str
    tts: str
    name: str
    native_name: str
    script: str
    script_start: int | None
    script_end: int | None
    allow_latin: bool
    fallback_voice: str


CA_VOICE_LANGUAGES: tuple[CaVoiceLanguage, ...] = (
    CaVoiceLanguage(
        "hi",
        "hi-IN",
        "Hindi",
        "हिन्दी",
        "Devanagari",
        0x0900,
        0x097F,
        False,
        "ये आज की खबर भारत से जुड़ी है। मूल बात ये है कि नीति, पड़ोस या अर्थव्यवस्था में कुछ नया हुआ है। "
        "परीक्षा में सामान्य अध्ययन के नीचे रखो। लिखते समय सिर्फ़ घटना मत लिखो, भारत का नज़रिया लिखो।",
    ),
    CaVoiceLanguage(
        "en",
        "en-IN",
        "English",
        "English",
        "Latin",
        None,
        None,
        True,
        "This story is about India. Something new has come up in policy, the neighbourhood, or the economy. "
        "Keep it under General Studies. When you write, do not only narrate the event — write India's point of view.",
    ),
    CaVoiceLanguage(
        "bn",
        "bn-IN",
        "Bengali",
        "বাংলা",
        "Bengali",
        0x0980,
        0x09FF,
        False,
        "এই খবরটা ভারতের সঙ্গে জড়িত। মূল কথা, নীতি, প্রতিবেশী বা অর্থনীতিতে কিছু নতুন হয়েছে। "
        "পরীক্ষায় জেনারেল স্টাডিজের নিচে রাখো। লেখার সময় শুধু ঘটনা নয়, ভারতের দৃষ্টিভঙ্গি লেখো।",
    ),
    CaVoiceLanguage(
        "ta",
        "ta-IN",
        "Tamil",
        "தமிழ்",
        "Tamil",
        0x0B80,
        0x0BFF,
        False,
        "இந்தச் செய்தி இந்தியாவுடன் தொடர்புடையது. கொள்கை, அண்டை நாடு அல்லது பொருளாதாரத்தில் புதிதாக ஏதோ வந்துள்ளது. "
        "தேர்வில் ஜெனரல் ஸ்டடீஸின் கீழ் வை. எழுதும்போது நிகழ்வை மட்டும் எழுதாதே, இந்தியாவின் பார்வையை எழுது.",
    ),
    CaVoiceLanguage(
        "te",
        "te-IN",
        "Telugu",
        "తెలుగు",
        "Telugu",
        0x0C00,
        0x0C7F,
        False,
        "ఈ వార్త భారతదేశానికి సంబంధించినది. విధానం, పొరుగు దేశాలు లేదా ఆర్థిక వ్యవస్థలో కొత్తది వచ్చింది. "
        "పరీక్షలో జనరల్ స్టడీస్ కింద ఉంచు. రాసేటప్పుడు సంఘటన మాత్రమే కాదు, భారత దృక్కోణం రాయి.",
    ),
    CaVoiceLanguage(
        "mr",
        "mr-IN",
        "Marathi",
        "मराठी",
        "Devanagari",
        0x0900,
        0x097F,
        False,
        "ही आजची बातमी भारताशी संबंधित आहे. धोरण, शेजारी देश किंवा अर्थव्यवस्थेत काही नवीन झाले आहे. "
        "परीक्षेत जनरल स्टडीजखाली ठेवा. लिहिताना फक्त घटना लिहू नका, भारताचा दृष्टिकोन लिहा.",
    ),
    CaVoiceLanguage(
        "kn",
        "kn-IN",
        "Kannada",
        "ಕನ್ನಡ",
        "Kannada",
        0x0C80,
        0x0CFF,
        False,
        "ಇದು ಭಾರತಕ್ಕೆ ಸಂಬಂಧಿಸಿದ ಸುದ್ದಿ. ನೀತಿ, ನೆರೆಹೊರೆ ಅಥವಾ ಆರ್ಥಿಕತೆಯಲ್ಲಿ ಹೊಸದು ಬಂದಿದೆ. "
        "ಪರೀಕ್ಷೆಯಲ್ಲಿ ಜನರಲ್ ಸ್ಟಡೀಸ್ ಕೆಳಗೆ ಇರಿಸಿ. ಬರೆಯುವಾಗ ಕೇವಲ ಘಟನೆ ಬೇಡ, ಭಾರತದ ನೋಟ ಬರೆಯಿರಿ.",
    ),
    CaVoiceLanguage(
        "gu",
        "gu-IN",
        "Gujarati",
        "ગુજરાતી",
        "Gujarati",
        0x0A80,
        0x0AFF,
        False,
        "આ આજની ખબર ભારત સાથે જોડાયેલી છે. નીતિ, પડોશ કે અર્થતંત્રમાં કંઈક નવું થયું છે. "
        "પરીક્ષામાં જનરલ સ્ટડીઝ નીચે મૂકો. લખતી વખતે માત્ર ઘટના નહીં, ભારતનો નજરિયો લખો.",
    ),
    CaVoiceLanguage(
        "ml",
        "ml-IN",
        "Malayalam",
        "മലയാളം",
        "Malayalam",
        0x0D00,
        0x0D7F,
        False,
        "ഇത് ഇന്ത്യയുമായി ബന്ധപ്പെട്ട വാർത്തയാണ്. നയം, അയൽരാജ്യം അല്ലെങ്കിൽ സമ്പദ്‌വ്യവസ്ഥയിൽ പുതിയത് വന്നിട്ടുണ്ട്. "
        "പരീക്ഷയിൽ ജനറൽ സ്റ്റഡീസിന് കീഴിൽ വയ്ക്കുക. എഴുതുമ്പോൾ സംഭവം മാത്രമല്ല, ഇന്ത്യയുടെ കാഴ്ചപ്പാട് എഴുതുക.",
    ),
    CaVoiceLanguage(
        "pa",
        "pa-IN",
        "Punjabi",
        "ਪੰਜਾਬੀ",
        "Gurmukhi",
        0x0A00,
        0x0A7F,
        False,
        "ਇਹ ਅੱਜ ਦੀ ਖ਼ਬਰ ਭਾਰਤ ਨਾਲ ਜੁੜੀ ਹੋਈ ਹੈ। ਨੀਤੀ, ਗੁਆਂਢ ਜਾਂ ਆਰਥਿਕਤਾ ਵਿੱਚ ਕੁਝ ਨਵਾਂ ਹੋਇਆ ਹੈ। "
        "ਪ੍ਰੀਖਿਆ ਵਿੱਚ ਜਨਰਲ ਸਟੱਡੀਜ਼ ਹੇਠ ਰੱਖੋ। ਲਿਖਦਿਆਂ ਸਿਰਫ਼ ਘਟਨਾ ਨਾ ਲਿਖੋ, ਭਾਰਤ ਦਾ ਨਜ਼ਰੀਆ ਲਿਖੋ।",
    ),
    CaVoiceLanguage(
        "od",
        "od-IN",
        "Odia",
        "ଓଡ଼ିଆ",
        "Odia",
        0x0B00,
        0x0B7F,
        False,
        "ଏହି ଖବର ଭାରତ ସହିତ ଜଡିତ। ନୀତି, ପଡ଼ୋଶୀ କିମ୍ବା ଅର୍ଥନୀତିରେ କିଛି ନୂଆ ହୋଇଛି। "
        "ପରୀକ୍ଷାରେ ଜେନେରାଲ ଷ୍ଟଡିଜ୍ ତଳେ ରଖ। ଲେଖିବାବେଳେ କେବଳ ଘଟଣା ନୁହେଁ, ଭାରତର ଦୃଷ୍ଟିକୋଣ ଲେଖ।",
    ),
)

DEFAULT_CA_VOICE_LANG = "hi"
_BY_CODE = {lang.code: lang for lang in CA_VOICE_LANGUAGES}


def resolve_ca_language(code: str | None) -> CaVoiceLanguage:
    key = (code or DEFAULT_CA_VOICE_LANG).strip().lower().replace("_", "-")
    if key.endswith("-in"):
        key = key.split("-", 1)[0]
    aliases = {"or": "od", "oriya": "od", "odia": "od", "bangla": "bn", "hindi": "hi"}
    key = aliases.get(key, key)
    return _BY_CODE.get(key, _BY_CODE[DEFAULT_CA_VOICE_LANG])


def ca_explain_use_llm(lang: CaVoiceLanguage) -> bool:
    """Listen: hi/en may use fast templates; other languages use LLM script + Sarvam TTS on cache miss."""
    from app.config.config import CA_EXPLAIN_LLM_ON_DEMAND

    if lang.code in ("hi", "en") and not CA_EXPLAIN_LLM_ON_DEMAND:
        return False
    return True


def languages_public() -> list[dict]:
    return [
        {
            "code": lang.code,
            "tts": lang.tts,
            "name": lang.name,
            "native_name": lang.native_name,
        }
        for lang in CA_VOICE_LANGUAGES
    ]
