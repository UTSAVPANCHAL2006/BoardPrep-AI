FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG PRELOAD_EMBEDDINGS=false
RUN if [ "$PRELOAD_EMBEDDINGS" = "true" ]; then python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"; fi

COPY app/ app/
COPY data/chroma/.gitkeep data/chroma/
COPY data/uploads/.gitkeep data/uploads/
COPY data/sample_daf_upsc_format_1.pdf data/

ENV PYTHONUNBUFFERED=1
ENV CHROMA_PATH=/app/data/chroma
ENV RAG_VECTORS_ENABLED=false

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
