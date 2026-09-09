import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.common.utils import llm_message_text, parse_json_response
from app.config.config import FALLBACK_CA_PATH, OPENAI_API_KEY
from app.prompts.enrich_prompt import (
    DAILY_ENRICH_SYSTEM_PROMPT,
    DAILY_ENRICH_THIN_RETRY_HINT,
    ENRICH_SYSTEM_PROMPT,
)
from app.schema.interview import EnrichedArticle

logger = get_logger(__name__)
_DAILY_ENRICH_DELAY_SEC = 0.5
_MAX_ENRICH_RETRIES = 2
_ENRICH_CONCURRENCY = 3

_PILLAR_EXTRA_HIGHLIGHTS: dict[str, list[str]] = {
    "GS1: Society": [
        "Track social indicators, constitutional provisions, and welfare scheme linkages for Prelims.",
    ],
    "GS1: Geography": [
        "Map locations, physical processes, and geophysical phenomena mentioned or implied in the headline.",
    ],
    "GS2: Polity": [
        "Constitutional articles, judicial pronouncements, and Centre-state dynamics are common Mains hooks.",
    ],
    "GS2: Governance": [
        "Link to transparency, accountability, e-governance, and flagship scheme implementation gaps.",
    ],
    "GS2: International Relations": [
        "Neighbourhood, multilateral forums, and India's strategic interests frame strong Mains IR answers.",
    ],
    "GS3: Economy": [
        "Connect to growth, inflation, fiscal policy, RBI/MPC, and sectoral reforms where relevant.",
    ],
    "GS3: Environment": [
        "Climate adaptation, biodiversity, COP commitments, and NDMA/disaster frameworks are high-yield Prelims topics.",
    ],
    "GS3: Internal Security": [
        "Terrorism, border management, cyber threats, and defence procurement often follow such headlines.",
    ],
    "GS3: Science & Tech": [
        "ISRO, biotech, IPR, and emerging tech policy are standard Prelims/Mains cross-links.",
    ],
}

_PILLAR_CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "GS3: Environment": [
        ("Climate adaptation", "Policy and infrastructure responses to reduce harm from climate impacts"),
        ("Disaster resilience", "Institutional and community capacity to absorb and recover from shocks"),
    ],
    "GS2: International Relations": [
        ("Neighbourhood First", "India's policy prioritising ties with South Asian and extended neighbours"),
        ("Transboundary cooperation", "Joint action across borders on rivers, disasters, trade, or security"),
    ],
    "GS3: Economy": [
        ("Fiscal policy", "Government taxation and spending choices affecting growth and stability"),
        ("Structural reforms", "Long-term changes to markets, labour, or regulation to raise productivity"),
    ],
    "GS2: Polity": [
        ("Separation of powers", "Constitutional division of authority among legislature, executive, and judiciary"),
        ("Judicial review", "Courts' power to examine constitutionality of laws and executive action"),
    ],
}


class NewsEnrichTool:

    def __init__(self, llm):
        self.llm = llm

    def _pillar(self, raw_article: dict) -> str:
        pillar = (raw_article.get("gs_pillar") or raw_article.get("daf_anchor", "")).replace("daily: ", "").strip()
        return pillar or "GS2: Governance"

    def _build_user_content(self, raw_article: dict, extra: str = "") -> str:
        pillar = self._pillar(raw_article)
        desc = (raw_article.get("description") or "").strip()
        thin_note = ""
        if len(desc) < 120:
            thin_note = (
                "\nNote: description is very short — expand from the headline and pillar using UPSC syllabus context."
            )
        parts = [
            f"GS pillar: {pillar}",
            f"Title: {raw_article.get('title', '')}",
            f"Description: {desc or '(none — infer from title)'}",
            f"Source: {raw_article.get('source', '')}",
            f"Published: {raw_article.get('published_at', '')}",
            f"DAF anchor: {raw_article.get('daf_anchor', '')}",
            thin_note,
        ]
        if extra:
            parts.append(extra)
        return "\n".join(p for p in parts if p)

    def _is_thin_payload(self, data: dict, description: str) -> bool:
        highlights = [h.strip() for h in (data.get("key_highlights") or []) if h and str(h).strip()]
        insights = (data.get("detailed_insights") or "").strip()
        concepts = data.get("key_concepts") or {}

        if len(highlights) < 3:
            return True
        if len(insights) < 100:
            return True
        if not concepts or len(concepts) < 2:
            return True

        desc_norm = description.strip().lower()
        if desc_norm:
            if insights.lower() == desc_norm:
                return True
            if len({h.lower() for h in highlights}) == 1 and highlights[0].lower() == desc_norm:
                return True
            if all(h.lower() == desc_norm or desc_norm in h.lower() and len(h) < len(desc_norm) + 20 for h in highlights):
                return True
        return False

    def _structured_fallback_notes(
        self, title: str, pillar: str, desc: str, source: str
    ) -> tuple[list[str], str, dict[str, str]]:
        subtopic = pillar.split(":", 1)[-1].strip() if ":" in pillar else pillar
        highlights: list[str] = []

        if desc and len(desc) > 30:
            highlights.append(f"News peg: {desc}")
        else:
            highlights.append(
                f"Editorial focus — {title} — flags an active {subtopic} theme in today's {source or 'newspapers'}."
            )

        highlights.append(
            f"UPSC {pillar}: structure Mains answers around context, stakeholders, policy gaps, and India's response."
        )
        highlights.append(
            f"Prelims angle — institutions, schemes, geography, and keyword facts tied to {subtopic}."
        )
        for extra in _PILLAR_EXTRA_HIGHLIGHTS.get(pillar, [])[:2]:
            highlights.append(extra)
        highlights = highlights[:5]

        insights = (
            f"This {source or 'newspaper'} story on \"{title}\" falls under {pillar}. "
            f"For Prelims, note bodies, treaties, schemes, and map-based facts linked to {subtopic}. "
            f"For Mains, analyse causes, unequal impacts, governance response, and a balanced way forward — "
            f"especially how Centre, states, and regional partners coordinate. "
        )
        if desc:
            insights += f"Editorial context: {desc}"

        concepts: dict[str, str] = {}
        for term, definition in _PILLAR_CONCEPTS.get(pillar, [])[:2]:
            concepts[term] = definition
        if not concepts:
            concepts[subtopic] = f"Syllabus area under {pillar} commonly tested in UPSC Prelims and Mains"
        title_terms = [w for w in re.findall(r"[A-Za-z]{5,}", title) if w.lower() not in {"india", "indian", "south", "asia"}]
        if title_terms and len(concepts) < 3:
            term = title_terms[0]
            if term not in concepts:
                concepts[term] = f"Key theme from today's headline relevant to {subtopic} questions"

        return highlights, insights, concepts

    def basic_enriched(self, raw_article: dict) -> EnrichedArticle:
        pillar = self._pillar(raw_article)
        title = (raw_article.get("title") or "").strip()
        desc = (raw_article.get("description") or "").strip()
        source = raw_article.get("source", "")
        highlights, insights, concepts = self._structured_fallback_notes(title, pillar, desc, source)
        gs_tags = [pillar]
        if pillar in _PILLAR_EXTRA_HIGHLIGHTS:
            gs_tags.append("Prelims")
        return EnrichedArticle(
            title=raw_article.get("title", ""),
            source=source,
            published_at=raw_article.get("published_at", ""),
            url=raw_article.get("url", ""),
            daf_anchor=raw_article.get("daf_anchor", ""),
            key_highlights=highlights,
            detailed_insights=insights,
            key_concepts=concepts,
            gs_tags=gs_tags,
            is_prelims_relevant=True,
        )

    async def enrich_article(self, raw_article, session_id: str = "", daily: bool = False):
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required for article enrichment")

        llm = self.llm.get_llm(temperature=0.2)
        from app.observability.langfuse_client import langchain_invoke_config

        system_prompt = DAILY_ENRICH_SYSTEM_PROMPT if daily else ENRICH_SYSTEM_PROMPT
        description = (raw_article.get("description") or "").strip()
        user_content = self._build_user_content(raw_article)
        config = langchain_invoke_config(
            session_id,
            run_name="ca_enrich_daily" if daily else "ca_enrich_article",
            tags=["upsc-interview", "current-affairs", "daily-ca" if daily else "daf-ca"],
        )

        last_err: Exception | None = None
        thin_retry_used = False
        for attempt in range(_MAX_ENRICH_RETRIES):
            try:
                response = await llm.ainvoke(
                    [SystemMessage(content=system_prompt), HumanMessage(content=user_content)],
                    config=config,
                )
                raw_text = llm_message_text(response)
                data = parse_json_response(raw_text)
                if daily and self._is_thin_payload(data, description) and not thin_retry_used:
                    thin_retry_used = True
                    user_content = self._build_user_content(raw_article, DAILY_ENRICH_THIN_RETRY_HINT)
                    logger.warning("Enrich output too thin — retrying with expansion hint")
                    await asyncio.sleep(1.5)
                    continue
                return EnrichedArticle(
                    title=raw_article.get("title", ""),
                    source=raw_article.get("source", ""),
                    published_at=raw_article.get("published_at", ""),
                    url=raw_article.get("url", ""),
                    daf_anchor=raw_article.get("daf_anchor", ""),
                    **data,
                )
            except json.JSONDecodeError as e:
                last_err = e
                logger.warning(f"Enrich JSON parse failed, retry {attempt + 1}/{_MAX_ENRICH_RETRIES}")
                await asyncio.sleep(2.0)
                continue
            except Exception as e:
                last_err = e
                if groq_error_is_rate_limit(e):
                    groq_mark_limited(e)
                    return self.basic_enriched(raw_article)
                logger.error(f"Error in NewsEnrichTool: {e}")
                raise CustomException("NewsEnrichTool Failed", e)

        logger.warning(f"Enrich failed after retries, using structured fallback: {last_err}")
        return self.basic_enriched(raw_article)

    async def enrich_articles(self, raw_articles, session_id: str = "", daily: bool = False):
        try:
            logger.info(f"NewsEnrichTool started with {len(raw_articles)} articles (daily={daily})")
            sem = asyncio.Semaphore(_ENRICH_CONCURRENCY)

            async def enrich_one(i: int, article: dict):
                async with sem:
                    enriched = await self.enrich_article(article, session_id=session_id, daily=daily)
                    if daily and i < len(raw_articles) - 1:
                        await asyncio.sleep(_DAILY_ENRICH_DELAY_SEC)
                    return enriched

            result = await asyncio.gather(
                *[enrich_one(i, article) for i, article in enumerate(raw_articles)]
            )
            logger.info("NewsEnrichTool completed")
            return list(result)

        except Exception as e:
            logger.error(f"Error in NewsEnrichTool: {str(e)}")
            raise CustomException("NewsEnrichTool Failed", e)

    def load_fallback_current_affairs(self):
        try:
            logger.info("NewsEnrichTool load_fallback started")
            if not FALLBACK_CA_PATH.exists():
                return []
            data = json.loads(FALLBACK_CA_PATH.read_text(encoding="utf-8"))
            articles = [EnrichedArticle.model_validate(item) for item in data]
            logger.info(f"NewsEnrichTool load_fallback completed: {len(articles)} articles")
            return articles

        except Exception as e:
            logger.error(f"Error in NewsEnrichTool: {str(e)}")
            raise CustomException("NewsEnrichTool Failed", e)
