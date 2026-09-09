import hashlib
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Literal

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.common.custom_exception import CustomException
from app.common.logger import get_logger
from app.config.config import CHROMA_DIR, RAG_VECTORS_ENABLED
from app.rag.embedding import Embedding
from app.schema.interview import EnrichedArticle

logger = get_logger(__name__)

DocType = Literal["current_affairs", "syllabus"]
SHARED_SYLLABUS_COLLECTION = "shared_syllabus"

_chroma_client = None
_bm25_index = {}


def shared_ca_collection_name(for_date: date | None = None) -> str:
    d = for_date or date.today()
    return f"shared_ca_{d.isoformat().replace('-', '_')}"


def collection_name(session_id: str, doc_type: DocType) -> str:
    safe_id = session_id.replace("-", "_")
    return f"session_{safe_id}_{doc_type}"


def resolve_collection(session_id: str, doc_type: DocType) -> str:
    if doc_type == "syllabus":
        return SHARED_SYLLABUS_COLLECTION
    if doc_type == "current_affairs":
        return shared_ca_collection_name()
    return collection_name(session_id, doc_type)


def _reset_chroma_storage() -> int:
    """Clear corrupt local Chroma files (sqlite + segment dirs). Keeps .gitkeep."""
    chroma_path = Path(CHROMA_DIR)
    if not chroma_path.exists():
        chroma_path.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for item in chroma_path.iterdir():
        if item.name == ".gitkeep":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
    return removed


def get_chroma_client():
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client
    for attempt in range(2):
        try:
            _chroma_client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
            )
            return _chroma_client
        except BaseException as e:
            _chroma_client = None
            if attempt == 0:
                n = _reset_chroma_storage()
                logger.warning(
                    f"Chroma init failed ({e}). Cleared {n} corrupt file(s) in {CHROMA_DIR}; retrying."
                )
            else:
                raise
    return _chroma_client


def article_to_document_text(article: EnrichedArticle) -> str:
    highlights = "\n".join(f"- {h}" for h in article.key_highlights)
    concepts = "\n".join(f"{k}: {v}" for k, v in article.key_concepts.items())
    tags = ", ".join(article.gs_tags)
    return (
        f"DAF Anchor: {article.daf_anchor}\n"
        f"Title: {article.title}\n"
        f"Source: {article.source} | Published: {article.published_at}\n"
        f"GS Tags: {tags}\n"
        f"Prelims relevant: {article.is_prelims_relevant}\n\n"
        f"Key Highlights:\n{highlights}\n\n"
        f"Detailed Insights:\n{article.detailed_insights}\n\n"
        f"Key Concepts:\n{concepts}"
    )


class Ingest:
    def __init__(self, embedding: Embedding):
        self.embedding = embedding

    def chunk_text(self, text, chunk_size=800, overlap=100):
        if len(text) <= chunk_size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end].strip())
            start = end - overlap
        return [c for c in chunks if c]

    def doc_id(self, session_id, doc_type, content, index):
        digest = hashlib.md5(content.encode()).hexdigest()[:12]
        return f"{session_id}_{doc_type}_{index}_{digest}"

    def ingest_corpus(self, items, doc_type: DocType, session_id: str) -> int:
        try:
            logger.info(f"Ingest started for session={session_id}, type={doc_type}")
            client = get_chroma_client()
            name = resolve_collection(session_id, doc_type)

            try:
                client.delete_collection(name)
            except Exception:
                pass

            collection = client.get_or_create_collection(
                name=name,
                metadata={
                    "hnsw:space": "cosine",
                    "created_at": str(time.time()),
                    "doc_type": doc_type,
                    "session_id": session_id if doc_type == "current_affairs" else "shared",
                },
            )

            documents = []
            ids = []
            metadatas = []

            if doc_type == "current_affairs":
                if not items:
                    return 0
                if isinstance(items[0], EnrichedArticle):
                    texts = [article_to_document_text(a) for a in items]
                else:
                    texts = [str(t) for t in items]
            else:
                if isinstance(items, (str, Path)):
                    path = Path(items)
                    texts = [path.read_text(encoding="utf-8", errors="ignore")] if path.exists() else [str(items)]
                elif isinstance(items, list):
                    texts = [str(t) for t in items]
                else:
                    texts = []

            chunk_index = 0
            for text in texts:
                for chunk in self.chunk_text(text):
                    doc_id = self.doc_id(session_id, doc_type, chunk, chunk_index)
                    documents.append(chunk)
                    ids.append(doc_id)
                    metadatas.append({"doc_type": doc_type, "session_id": session_id})
                    chunk_index += 1

            if not documents:
                return 0

            if not RAG_VECTORS_ENABLED:
                _bm25_index[name] = {"documents": documents, "ids": ids}
                logger.info(f"Ingest completed (BM25-only): {len(documents)} chunks in {name}")
                return len(documents)

            vectors = self.embedding.embed_documents(documents)
            collection.add(ids=ids, documents=documents, embeddings=vectors, metadatas=metadatas)

            _bm25_index[name] = {"documents": documents, "ids": ids}
            logger.info(f"Ingest completed: {len(documents)} chunks")
            return len(documents)

        except Exception as e:
            logger.error(f"Error in Ingest: {str(e)}")
            raise CustomException("Ingest Failed", e)

    def ingest_shared_syllabus(self, syllabus_path) -> int:
        """Ingest syllabus once into global shared collection."""
        path = Path(syllabus_path)
        if not path.exists():
            return 0
        content_hash = hashlib.md5(path.read_bytes()).hexdigest()
        name = SHARED_SYLLABUS_COLLECTION
        cached = _bm25_index.get(name)
        if cached and cached.get("documents") and not RAG_VECTORS_ENABLED:
            logger.info("Shared syllabus BM25 cache hit")
            return len(cached["documents"])
        client = get_chroma_client()
        try:
            col = client.get_collection(SHARED_SYLLABUS_COLLECTION)
            meta = col.metadata or {}
            if meta.get("content_hash") == content_hash and col.count() > 0:
                logger.info("Shared syllabus cache hit")
                return col.count()
        except Exception:
            pass
        count = self.ingest_corpus(syllabus_path, doc_type="syllabus", session_id="shared")
        try:
            col = client.get_collection(SHARED_SYLLABUS_COLLECTION)
            col.modify(metadata={"content_hash": content_hash, "created_at": str(time.time())})
        except Exception:
            pass
        return count

    def ingest_shared_current_affairs(self, articles: list[EnrichedArticle]) -> int:
        """Ingest today's CA into one shared Chroma collection (all users)."""
        if not articles:
            return 0
        client = get_chroma_client()
        name = shared_ca_collection_name()
        try:
            col = client.get_collection(name)
            if col.count() > 0:
                logger.info(f"Shared CA cache hit in Chroma: {name} ({col.count()} chunks)")
                return col.count()
        except Exception:
            pass
        return self.ingest_corpus(articles, doc_type="current_affairs", session_id="shared")
