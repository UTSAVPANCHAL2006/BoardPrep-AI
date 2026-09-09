from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.config.config import HF_EMBEDDING_MODEL, RAG_VECTORS_ENABLED

logger = get_logger(__name__)

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

    def embed_documents(self, texts):
        if not RAG_VECTORS_ENABLED or self.embeddings is None:
            raise CustomException("Embedding disabled", ValueError("RAG_VECTORS_ENABLED=false"))
        try:
            return self.embeddings.embed_documents(texts)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)

    def embed_query(self, query):
        if not RAG_VECTORS_ENABLED or self.embeddings is None:
            raise CustomException("Embedding disabled", ValueError("RAG_VECTORS_ENABLED=false"))
        try:
            return self.embeddings.embed_query(query)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)
