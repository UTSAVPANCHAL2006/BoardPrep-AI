import json
import re

from app.schema.interview import ChatTurn, DAFProfile, EnrichedArticle


def llm_message_text(response) -> str:
    """Flatten Groq/LangChain content (gpt-oss may hide text in reasoning / additional_kwargs)."""
    content = getattr(response, "content", response)
    text = ""
    if content is None:
        text = ""
    elif isinstance(content, str):
        text = content
    elif isinstance(content, list):
        texts: list[str] = []
        reasoning: list[str] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
                continue
            if isinstance(block, dict):
                btype = str(block.get("type") or "").lower()
                chunk = block.get("text") or block.get("content") or block.get("reasoning") or ""
                if isinstance(chunk, list):
                    chunk = llm_message_text(chunk)
                chunk = str(chunk) if chunk else ""
                if btype in {"reasoning", "thinking"}:
                    reasoning.append(chunk)
                elif chunk:
                    texts.append(chunk)
                continue
            btype = str(getattr(block, "type", "")).lower()
            chunk = getattr(block, "text", None) or getattr(block, "content", None)
            chunk = str(chunk) if chunk else ""
            if btype in {"reasoning", "thinking"}:
                reasoning.append(chunk)
            elif chunk:
                texts.append(chunk)
        text = "\n".join(t.strip() for t in texts if t and str(t).strip())
        if not text.strip():
            text = "\n".join(t.strip() for t in reasoning if t and str(t).strip())
    else:
        text = str(content)

    if not (text or "").strip():
        extra = getattr(response, "additional_kwargs", None) or {}
        for key in ("reasoning_content", "reasoning", "parsed"):
            if extra.get(key):
                text = str(extra[key])
                break
    return (text or "").strip()


def parse_json_response(content: str) -> dict:
    cleaned = llm_message_text(content) if not isinstance(content, str) else content.strip()
    cleaned = cleaned.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        obj_match = re.search(r"\{[\s\S]*\}", cleaned)
        if obj_match:
            cleaned = obj_match.group(0)

    for candidate in (cleaned, repair_json(cleaned)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("Could not parse JSON from LLM response", cleaned[:200], 0)


def repair_json(text: str) -> str:
    """Fix common LLM JSON mistakes like mismatched brackets in list items."""
    repaired = text
    repaired = re.sub(r"\(([^)]+)\"\)", r'(\1)"', repaired)
    repaired = re.sub(r'\["([^"\]]*?)"\)', r'["\1"]', repaired)
    return repaired


def profile_summary(profile: DAFProfile) -> str:
    return (
        f"Hometown: {profile.hometown}\n"
        f"Education: {', '.join(profile.education)}\n"
        f"Work: {', '.join(profile.work_experience)}\n"
        f"Hobbies: {', '.join(profile.hobbies)}\n"
        f"Optional subject: {profile.optional_subject}\n"
        f"Service preferences: {', '.join(profile.service_preferences)}"
    )


def history_text(history: list[ChatTurn]) -> str:
    if not history:
        return "(no prior exchanges)"
    lines = [f"{turn.role.upper()}: {turn.content}" for turn in history[-6:]]
    return "\n".join(lines)


def build_daf_topic_stack(profile: DAFProfile) -> list[str]:
    """Ordered DAF anchors — one per question rotation across all phases."""
    anchors: list[str] = []
    if profile.hometown:
        anchors.append(f"hometown: {profile.hometown}")
    for hobby in profile.hobbies[:2]:
        anchors.append(f"hobby: {hobby}")
    for edu in profile.education[:2]:
        anchors.append(f"education: {edu}")
    for work in profile.work_experience[:2]:
        anchors.append(f"work: {work}")
    if profile.optional_subject:
        anchors.append(f"optional subject: {profile.optional_subject}")
    for pref in profile.service_preferences[:1]:
        anchors.append(f"service preference: {pref}")
    return anchors or ["background and motivation"]


def ca_board_question_word_limits(
    interview_mode: str,
    *,
    for_voice: bool = False,
) -> int:
    """CA interview questions only — keep shorter than other phases."""
    quick = (interview_mode or "full").lower() == "quick"
    display_cap, voice_cap = (16, 22) if quick else (20, 26)
    return voice_cap if for_voice else display_cap


def sanitize_ca_board_question(text: str, max_words: int = 20) -> str:
    """CA phase: one short angle — news OR DAF link, not a bundled essay."""
    cleaned = sanitize_board_question(text, max_words=max_words)
    if not cleaned:
        return cleaned

    lower = cleaned.lower()
    for splitter in (
        ", given your",
        " given your",
        ", considering your",
        " considering your",
        ", in light of your",
        " in light of your",
        " how would you apply",
        " how would you integrate",
        " how would you use",
        ", and how",
        "; how would",
        " aur isse",
        " aur aap isse",
    ):
        idx = lower.find(splitter)
        if idx > 10:
            cleaned = cleaned[:idx].rstrip(",;:")
            if not cleaned.endswith("?"):
                cleaned += "?"
            lower = cleaned.lower()

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(",;:")
        if not cleaned.endswith("?"):
            cleaned += "?"

    return cleaned.strip()


def sanitize_board_question(text: str, max_words: int = 32) -> str:
    """Keep questions short and single-threaded like a real UPSC board."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return cleaned

    if cleaned.count("?") > 1:
        first_q = cleaned.find("?")
        cleaned = cleaned[: first_q + 1]

    q_idx = cleaned.find("?")
    if q_idx != -1:
        cleaned = cleaned[: q_idx + 1]

    if "?" not in cleaned:
        parts = re.split(r"(?<=[.!?])\s+", cleaned)
        cleaned = parts[0] if parts else cleaned

    # Drop compound follow-ups (English + Hinglish/Hindi)
    lower = cleaned.lower()
    for splitter in (
        ", and ",
        "; and ",
        " and in ",
        " — and ",
        ", aur ",
        "; aur ",
        " aur aap ",
        " aur aapke ",
        ", and how ",
        ", and what ",
        ", और ",
        "; और ",
    ):
        idx = lower.find(splitter)
        if idx > 12:
            cleaned = cleaned[:idx].rstrip(",;:")
            if not cleaned.endswith("?"):
                cleaned += "?"
            break

    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]).rstrip(",;:")
        if not cleaned.endswith("?"):
            cleaned += "?"

    return cleaned.strip()


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{4,}", (text or "").lower()))


def ca_grounding_score(question: str, article: EnrichedArticle) -> float:
    """Score 0-1: how well the question references the featured CA article."""
    q_tokens = tokenize(question)
    if not q_tokens:
        return 0.0

    signals: list[float] = []

    title_tokens = tokenize(article.title)
    if title_tokens:
        signals.append(len(q_tokens & title_tokens) / max(len(title_tokens), 1))

    for concept in article.key_concepts:
        concept_tokens = tokenize(concept)
        if concept_tokens:
            signals.append(len(q_tokens & concept_tokens) / max(len(concept_tokens), 1))

    for highlight in article.key_highlights[:2]:
        h_tokens = tokenize(highlight)
        if h_tokens:
            signals.append(len(q_tokens & h_tokens) / max(len(h_tokens), 1))

    if article.title.lower() in question.lower():
        signals.append(1.0)

    return max(signals) if signals else 0.0


def is_ca_grounded(question: str, article: EnrichedArticle, threshold: float = 0.12) -> bool:
    return ca_grounding_score(question, article) >= threshold


def format_ca_article_for_prompt(article: EnrichedArticle) -> str:
    highlights = "\n".join(f"- {h}" for h in article.key_highlights[:3])
    return (
        f"Title: {article.title}\n"
        f"Source: {article.source} | DAF link: {article.daf_anchor}\n"
        f"Key highlights:\n{highlights}\n"
        f"Summary: {article.detailed_insights[:400]}"
    )
