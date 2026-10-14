"""Text embeddings for vector search (off on low-memory hosts: then keyword search only)."""

from app.common.custom_exception import CustomException
from app.common.logger import getLogger
from app.config.config import HF_EMBEDDING_MODEL, RAG_VECTORS_ENABLED

logger = getLogger(__name__)

_embeddings = None


class Embedding:
    def __init__(self):
        if not RAG_VECTORS_ENABLED:
            self.embeddings = None
            return
        global _embeddings
        if _embeddings is None:
            logger.info("Loading embedding model")
            from langchain_huggingface import HuggingFaceEmbeddings

            _embeddings = HuggingFaceEmbeddings(
                model_name=HF_EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        self.embeddings = _embeddings

    def embedDocuments(self, texts):
        if not RAG_VECTORS_ENABLED or self.embeddings is None:
            raise CustomException("Embedding disabled", ValueError("RAG_VECTORS_ENABLED=false"))
        try:
            return self.embeddings.embedDocuments(texts)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)

    def embedQuery(self, query):
        if not RAG_VECTORS_ENABLED or self.embeddings is None:
            raise CustomException("Embedding disabled", ValueError("RAG_VECTORS_ENABLED=false"))
        try:
            return self.embeddings.embedQuery(query)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)
