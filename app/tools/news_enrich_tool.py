"""Saved current-affairs articles for the interview's current-affairs round (curated, pre-enriched notes).

The live newspaper fetch and LLM enrichment pipeline was removed with the Daily CA page: the interview asks about
a saved set, so a news API outage or rate limit can never stall a mock interview."""

import json

from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.config.config import FALLBACK_CA_PATH
from app.schema.interview import EnrichedArticle

logger = getLogger(__name__)


class NewsEnrichTool:
    def __init__(self, llm=None):
        self.llm = llm

    def loadFallbackCurrentAffairs(self):
        try:
            if not FALLBACK_CA_PATH.exists():
                return []
            data = json.loads(FALLBACK_CA_PATH.read_text(encoding="utf-8"))
            articles = [EnrichedArticle.model_validate(item) for item in data]
            logger.info(f"Saved current affairs loaded: {len(articles)} articles")
            return articles
        except Exception as e:
            logger.error(f"Error loading saved current affairs: {e}")
            raise CustomException("NewsEnrichTool Failed", e)
