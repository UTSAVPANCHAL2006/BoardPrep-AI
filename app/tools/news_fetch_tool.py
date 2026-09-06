import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.config.config import DAILY_CA_ARTICLE_COUNT, NEWSDATA_API_KEY

IST = ZoneInfo("Asia/Kolkata")

logger = get_logger(__name__)

NEWSDATA_BASE = "https://newsdata.io/api/1/latest"

SKIP_PATTERNS = re.compile(
    r"birthday|first salary|spent it all|file photo|celebrating|viral video|meme|"
    r"horoscope|zodiac|bollywood gossip|cricket score|ipl match|crossword|glp-1|"
    r"fitness coach|mural|film premiere|horoscope|"
    r"courtroom drama|tollywood|birth centenary|hundred years ago|lecture in bombay|"
    r"ferry with \d+ on board|rescued after snag|fair eyeing|sanatani people|"
    r"scribes allege|beat them with sticks|brands overreacting|manufactured outrage|"
    r"^watch:|^video:|top news of the day|explainspeaking| writes:|upsc essentials|"
    r"daily subject-wise quiz|neet-pg|neet pg|hockey teams|junior asia cup",
    re.I,
)

LOW_VALUE_PATTERNS = re.compile(
    r"courtroom drama|brands overreacting|uttam kumar|tollywood|ferry with|"
    r"fair eyeing|scribes allege|dimagi naxal|fading fear of hiv|trade pact to be finalised",
    re.I,
)

CA_NEWSPAPER_DOMAINS = "thehindu,indianexpress"

ALLOWED_CA_SOURCE_IDS = frozenset({"thehindu", "indianexpress"})

ALLOWED_CA_DOMAIN_FRAGMENTS = ("thehindu.com", "indianexpress.com")

SOURCE_DISPLAY_NAMES = {
    "thehindu": "The Hindu",
    "indianexpress": "Indian Express",
}

CA_FETCH_BATCHES = [
    {"domains": "thehindu", "q": "exports"},
    {"domains": "thehindu", "q": "Jaishankar"},
    {"domains": "thehindu", "q": "Ladakh"},
    {"domains": "thehindu", "q": "Belgium"},
    {"domains": "thehindu", "q": "SCO"},
    {"domains": "thehindu", "q": "climate"},
    {"domains": "thehindu", "q": "glacial"},
    {"domains": "thehindu", "q": "police"},
    {"domains": "indianexpress", "q": "economy"},
    {"domains": "indianexpress", "q": "Bihar"},
]

UPSC_BOOST_WORDS = [
    "government", "policy", "scheme", "ministry", "parliament", "bill", "court",
    "governance", "reform", "budget", "rbi", "election", "diplomacy", "trade",
    "climate", "defence", "supreme court", "constitution", "welfare", "inflation",
    "gdp", "export", "jaishankar", "ladakh", "belgium", "sco", "modi", "ukraine",
    "russia", "glacial", "glof", "thorium", "norway", "iran", "police", "isro",
    "nuclear", "solar", "bihar", "manufacturing", "forex", "reserves", "bar council",
    "el nino", "sudan", "raksha", "biotechnology", "jal sanchay", "grain storage",
]

DAILY_CA_PILLARS = [
    {"keywords": ["parliament", "supreme court", "constitution", "election", "governor", "judiciary"], "pillar": "GS2: Polity"},
    {"keywords": ["gdp", "rbi", "inflation", "fiscal", "economy", "trade", "budget", "monetary"], "pillar": "GS3: Economy"},
    {"keywords": ["diplomacy", "bilateral", "foreign", "summit", "china", "nepal", "pakistan"], "pillar": "GS2: International Relations"},
    {"keywords": ["climate", "environment", "flood", "glacier", "wetland", "disaster"], "pillar": "GS3: Environment"},
    {"keywords": ["space", "technology", "missile", "defence", "isro", "quantum", "ai"], "pillar": "GS3: Science & Tech"},
    {"keywords": ["agriculture", "farmer", "msp", "crop", "food security"], "pillar": "GS3: Agriculture"},
    {"keywords": ["welfare", "tribal", "women", "social justice", "scheme"], "pillar": "GS2: Social Justice"},
    {"keywords": ["security", "terror", "border", "army", "cyber", "militant"], "pillar": "GS3: Internal Security"},
]


class NewsFetchTool:

    async def fetch_daily_upsc_bundle(self, target: int | None = None) -> list[dict]:
        """Today's 10 headlines from The Hindu and Indian Express only."""
        target = target or DAILY_CA_ARTICLE_COUNT
        try:
            logger.info(f"NewsFetchTool fetch_daily_upsc_bundle started (target={target})")
            if not NEWSDATA_API_KEY:
                raise RuntimeError("NEWSDATA_API_KEY not set")

            raw_pool: list[dict] = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for batch in CA_FETCH_BATCHES:
                    batch_articles = await self.fetch_ca_batch(client, batch)
                    raw_pool.extend(batch_articles)
                    await asyncio.sleep(3.0)

                if len(raw_pool) < target:
                    logger.info("CA batches thin — combined Hindu+Express fetch for today")
                    extra = await self.fetch_ca_batch(
                        client,
                        {"domains": CA_NEWSPAPER_DOMAINS, "q": "India"},
                    )
                    raw_pool.extend(extra)

            if not raw_pool:
                raise RuntimeError("No articles from The Hindu or Indian Express for today")

            unique = self.dedupe(raw_pool)
            scored = [(self.daily_score(article), article) for article in unique]
            scored.sort(key=lambda x: x[0], reverse=True)

            picked = self.pick_diverse_daily([a for _, a in scored], target)
            logger.info(
                f"NewsFetchTool fetch_daily_upsc_bundle completed: {len(picked)} articles "
                f"from {[a.get('source') for a in picked]}"
            )
            return picked

        except Exception as e:
            logger.error(f"Error in NewsFetchTool fetch_daily_upsc_bundle: {e}")
            raise CustomException("NewsFetchTool Daily Bundle Failed", e)

    def is_allowed_ca_item(self, item: dict) -> bool:
        source_id = (item.get("source_id") or "").lower().strip()
        link = (item.get("link") or "").lower()
        source_name = (item.get("source_name") or "").lower()

        if source_id in ALLOWED_CA_SOURCE_IDS:
            return True
        if any(fragment in link for fragment in ALLOWED_CA_DOMAIN_FRAGMENTS):
            return True
        allowed_names = ("the hindu", "indian express")
        return any(name in source_name for name in allowed_names)

    def tag_pillar(self, title: str, desc: str) -> str:
        text = f"{title} {desc}".lower()
        best_pillar = "GS2: Governance"
        best_score = 0
        for entry in DAILY_CA_PILLARS:
            score = sum(1 for kw in entry["keywords"] if kw in text)
            if score > best_score:
                best_score = score
                best_pillar = entry["pillar"]
        return best_pillar

    async def newsdata_get(
        self, client: httpx.AsyncClient, params: dict, retries: int = 4
    ) -> dict:
        """GET NewsData with 429 backoff."""
        domain = params.get("domain", "?")
        for attempt in range(retries):
            try:
                resp = await client.get(NEWSDATA_BASE, params=params)
                if resp.status_code == 429:
                    wait = min(30, 3 * (2 ** attempt))
                    logger.warning(f"NewsData 429 ({domain}), retry in {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as e:
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error(f"CA batch fetch failed ({domain}): {e}")
        return {}

    async def fetch_ca_batch(self, client: httpx.AsyncClient, batch: dict) -> list[dict]:
        params = {
            "apikey": NEWSDATA_API_KEY,
            "country": "in",
            "language": "en",
            "q": batch["q"],
            "domain": batch["domains"],
        }
        payload = await self.newsdata_get(client, params)
        if not payload:
            return []

        articles = []
        for item in (payload.get("results") or [])[:20]:
            if not self.is_allowed_ca_item(item):
                continue
            published = item.get("pubDate") or item.get("published_at") or ""
            if not self.is_edition_relevant(published):
                continue
            title = (item.get("title") or "").strip()
            desc = (item.get("description") or item.get("content") or "").strip()
            if not title or SKIP_PATTERNS.search(f"{title} {desc}"):
                continue
            if title.lower().startswith("watch:") or title.lower().startswith("video:"):
                continue
            pillar = self.tag_pillar(title, desc)
            articles.append({
                "title": title,
                "description": desc,
                "published_at": self.format_published_ist(published),
                "_published_raw": published,
                "source": self.display_source(item),
                "url": item.get("link") or "",
                "daf_anchor": f"daily: {pillar}",
                "gs_pillar": pillar,
            })
        return articles

    def display_source(self, item: dict) -> str:
        source_id = (item.get("source_id") or "").lower().strip()
        if source_id in SOURCE_DISPLAY_NAMES:
            return SOURCE_DISPLAY_NAMES[source_id]
        link = (item.get("link") or "").lower()
        for fragment, label in (
            ("thehindu.com", "The Hindu"),
            ("indianexpress.com", "Indian Express"),
        ):
            if fragment in link:
                return label
        return "Indian Express"

    def format_published_ist(self, published: str) -> str:
        dt = self.parse_published(published)
        if dt is None:
            return (published or "")[:10]
        return dt.astimezone(IST).strftime("%Y-%m-%d")

    def is_edition_relevant(self, published: str) -> bool:
        """Today's print edition: from yesterday 3 PM IST through now (newspapers publish evening before)."""
        dt = self.parse_published(published)
        if dt is None:
            return False
        dt_ist = dt.astimezone(IST)
        now_ist = datetime.now(IST)
        today = now_ist.date()
        yesterday = today - timedelta(days=1)
        if dt_ist.date() == today:
            return True
        if dt_ist.date() == yesterday and dt_ist.hour >= 15:
            return True
        return False

    def is_today(self, published: str) -> bool:
        """Alias for edition window — kept for tests."""
        return self.is_edition_relevant(published)

    def is_recent(self, published: str, hours: int = 48) -> bool:
        dt = self.parse_published(published)
        if dt is None:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)

    def parse_published(self, raw: str) -> datetime | None:
        if not raw:
            return None
        raw = raw.strip()
        try:
            if "T" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw):
                return datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return parsedate_to_datetime(raw)
        except (ValueError, TypeError):
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                return None

    def daily_score(self, article: dict) -> float:
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        score = 0.0
        for word in UPSC_BOOST_WORDS:
            if word in text:
                score += 2.0
        if LOW_VALUE_PATTERNS.search(text):
            score -= 12.0
        source = (article.get("source") or "").lower()
        if "hindu" in source or "indian express" in source:
            score += 4.0
        raw_pub = article.get("_published_raw") or article.get("published_at", "")
        dt = self.parse_published(raw_pub)
        if dt:
            age_hours = (datetime.now(IST) - dt.astimezone(IST)).total_seconds() / 3600
            score += max(0, 8 - age_hours / 6)
        return score

    def title_fingerprint(self, title: str) -> str:
        words = re.sub(r"[^\w\s]", " ", title.lower()).split()
        return " ".join(words[:12])

    def pick_diverse_daily(self, articles: list[dict], target: int) -> list[dict]:
        by_pillar: dict[str, list[dict]] = {}
        for article in articles:
            pillar = article.get("gs_pillar") or article.get("daf_anchor", "general")
            by_pillar.setdefault(pillar, []).append(article)

        picked: list[dict] = []
        seen_titles: set[str] = set()
        seen_fingerprints: set[str] = set()

        def take(article: dict) -> bool:
            title_key = (article.get("title") or "").strip().lower()
            fp = self.title_fingerprint(article.get("title") or "")
            if title_key in seen_titles or fp in seen_fingerprints:
                return False
            picked.append(article)
            seen_titles.add(title_key)
            seen_fingerprints.add(fp)
            return True

        per_source = max(1, target // 2)
        by_score = sorted(articles, key=self.daily_score, reverse=True)
        for source_label in ("The Hindu", "Indian Express"):
            count = 0
            for article in by_score:
                if article.get("source") != source_label:
                    continue
                if take(article):
                    count += 1
                if count >= per_source:
                    break

        for pillar in DAILY_CA_PILLARS:
            for article in by_pillar.get(pillar["pillar"], []):
                if take(article):
                    break
            if len(picked) >= target:
                break

        for article in by_score:
            if len(picked) >= target:
                break
            take(article)

        return picked[:target]

    def dedupe(self, articles):
        seen_hash: set[str] = set()
        seen_fp: set[str] = set()
        unique = []
        for article in articles:
            title = (article.get("title") or "").strip()
            key = hashlib.md5(title.lower().encode()).hexdigest()
            fp = self.title_fingerprint(title)
            if key in seen_hash or fp in seen_fp:
                continue
            seen_hash.add(key)
            seen_fp.add(fp)
            unique.append(article)
        return unique
