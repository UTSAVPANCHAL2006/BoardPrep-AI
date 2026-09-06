import asyncio
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.rag.embedding import Embedding
from app.rag.ingest import _bm25_index, get_chroma_client, resolve_collection

logger = get_logger(__name__)


class Retriever:
    def __init__(self, embedding: Embedding):
        self.embedding = embedding

    def ensure_bm25_index(self, collection_key: str) -> None:
        if collection_key in _bm25_index and "retriever" in _bm25_index[collection_key]:
            return
        try:
            client = get_chroma_client()
            collection = client.get_collection(collection_key)
            if collection.count() == 0:
                return
            result = collection.get(include=["documents"])
            documents = result.get("documents") or []
            ids = result.get("ids") or []
            if documents:
                lc_docs = [Document(page_content=d) for d in documents]
                retriever = BM25Retriever.from_documents(lc_docs)
                retriever.k = 10
                _bm25_index[collection_key] = {
                    "documents": documents,
                    "ids": ids,
                    "retriever": retriever,
                }
        except Exception:
            return

    def bm25_search(self, collection_key, query, top_k):
        self.ensure_bm25_index(collection_key)
        index = _bm25_index.get(collection_key)
        if not index or "retriever" not in index:
            return []
        retriever: BM25Retriever = index["retriever"]
        retriever.k = top_k
        docs = retriever.invoke(query)
        # Return matched document content along with normalized score representation
        return [(doc.page_content, 1.0 / (idx + 1)) for idx, doc in enumerate(docs)]

    def vector_search(self, collection_key, query, top_k):
        client = get_chroma_client()
        try:
            collection = client.get_collection(collection_key)
        except Exception:
            return []
        if collection.count() == 0:
            return []
        query_vec = self.embedding.embed_query(query)
        results = collection.query(query_embeddings=[query_vec], n_results=top_k)
        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        return [(doc, 1.0 / (1.0 + float(dist))) for doc, dist in zip(docs, distances)]

    async def hybrid_retrieve_async(self, query, session_id, doc_type="current_affairs", top_k=4):
        from app.observability.langfuse_client import observation_context

        try:
            logger.info(f"Retriever started: query={query[:50]}...")
            name = resolve_collection(session_id, doc_type)

            with observation_context(
                name="rag_hybrid_retrieve",
                session_id=session_id,
                as_type="retrieval",
                input={"query": query, "doc_type": doc_type, "top_k": top_k},
            ):
                # Execute vector_search and bm25_search concurrently in threadpool to avoid blocking event loop
                vector_task = asyncio.to_thread(self.vector_search, name, query, top_k * 2)
                bm25_task = asyncio.to_thread(self.bm25_search, name, query, top_k * 2)

                vector_hits, bm25_hits = await asyncio.gather(vector_task, bm25_task)

                fused = {}
                for doc, score in vector_hits:
                    fused[doc] = fused.get(doc, 0.0) + score
                for doc, score in bm25_hits:
                    fused[doc] = fused.get(doc, 0.0) + score * 0.5

                ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
                docs = [doc for doc, _ in ranked[:top_k]]
                logger.info(f"Retriever got {len(docs)} docs from {name}")
                return docs

        except Exception as e:
            logger.error(f"Error in Retriever: {str(e)}")
            raise CustomException("Retriever Failed", e)

    def hybrid_retrieve(self, query, session_id, doc_type="current_affairs", top_k=4):
        from app.observability.langfuse_client import observation_context

        try:
            name = resolve_collection(session_id, doc_type)
            with observation_context(
                name="rag_hybrid_retrieve_sync",
                session_id=session_id,
                as_type="retrieval",
                input={"query": query, "doc_type": doc_type, "top_k": top_k},
            ):
                vector_hits = self.vector_search(name, query, top_k=top_k * 2)
                bm25_hits = self.bm25_search(name, query, top_k=top_k * 2)

                fused = {}
                for doc, score in vector_hits:
                    fused[doc] = fused.get(doc, 0.0) + score
                for doc, score in bm25_hits:
                    fused[doc] = fused.get(doc, 0.0) + score * 0.5

                ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
                return [doc for doc, _ in ranked[:top_k]]
        except Exception as e:
            logger.error(f"Error in Retriever: {str(e)}")
            raise CustomException("Retriever Failed", e)

