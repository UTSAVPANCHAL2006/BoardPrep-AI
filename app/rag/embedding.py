from langchain_huggingface import HuggingFaceEmbeddings

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.config.config import HF_EMBEDDING_MODEL

logger = get_logger(__name__)

_embeddings = None


class Embedding:
    def __init__(self):
        global _embeddings
        if _embeddings is None:
            logger.info("Loading embedding model")
            _embeddings = HuggingFaceEmbeddings(
                model_name=HF_EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        self.embeddings = _embeddings

    def embed_documents(self, texts):
        try:
            return self.embeddings.embed_documents(texts)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)

    def embed_query(self, query):
        try:
            return self.embeddings.embed_query(query)
        except Exception as e:
            logger.error(f"Error in Embedding: {str(e)}")
            raise CustomException("Embedding Failed", e)
