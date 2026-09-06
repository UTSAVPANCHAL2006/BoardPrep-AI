# System Architecture — BoardPrep AI

This document describes how the UPSC mock interview + daily CA voice prototype is structured. All diagrams use [Mermaid](https://mermaid.js.org/) and render on GitHub.

---

## 1. System context

Who talks to what at the highest level.

```mermaid
flowchart TB
    Aspirant([UPSC Aspirant])

    subgraph BoardPrep["BoardPrep AI"]
        APP[Web app + API]
    end

    GROQ[Groq LLM]
    SARVAM[Sarvam STT/TTS]
    NEWS[NewsData.io]
    REDIS[(Redis)]
    LF[Langfuse]

    Aspirant -->|Browser| APP
    APP --> GROQ
    APP --> SARVAM
    APP --> NEWS
    APP --> REDIS
    APP --> LF
```

---

## 2. Container diagram

Major deployable parts inside the repository.

```mermaid
flowchart TB
    subgraph Browser["Browser (Next.js 15)"]
        HOME[Home / DAF upload]
        INT[Interview room]
        CA[Daily CA voice page]
        FB[Feedback report]
    end

    subgraph Server["FastAPI backend"]
        API[REST API layer]
        GRAPH[LangGraph interview agent]
        TOOLS[Tools layer]
        RAG[RAG pipeline]
        OBS[Langfuse observability]
    end

    subgraph Storage["Local / external storage"]
        CHROMA[(ChromaDB)]
        REDIS[(Redis)]
        DISK[PDF uploads + fallback JSON]
    end

    subgraph External["External APIs"]
        GROQ[Groq LLM]
        SARVAM[Sarvam voice]
        NEWS[NewsData.io]
    end

    HOME --> API
    INT --> API
    CA --> API
    FB --> API

    API --> GRAPH
    API --> TOOLS
    GRAPH --> TOOLS
    GRAPH --> RAG
    TOOLS --> RAG
    API --> OBS

    RAG --> CHROMA
    API --> REDIS
    TOOLS --> DISK
    TOOLS --> GROQ
    TOOLS --> SARVAM
    TOOLS --> NEWS
```

---

## 3. Interview flow (sequence & streaming)

One full turn after the session has started (showing low-latency SSE audio streaming).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Next.js UI
    participant API as FastAPI
    participant STT as Sarvam STT
    participant Graph as LangGraph
    participant LLM as Groq LLM
    participant RAG as Async Hybrid RAG
    participant TTS as Sarvam TTS

    User->>UI: Speaks answer (mic)
    UI->>API: POST /respond-stream (audio)
    API->>STT: Transcribe (saaras:v3 codemix)
    STT-->>API: transcript

    API->>Graph: run turn(state, transcript)
    Graph->>LLM: Evaluate answer
    LLM-->>Graph: clarity, DAF flags, notes

    Graph->>Graph: Router (probe / pivot / advance_phase)
    Graph->>RAG: Concurrent vector_search + LangChain BM25
    RAG-->>Graph: fused context chunks

    Graph->>LLM: Generate next question
    LLM-->>Graph: question + question_voice (Hindi)
    Graph-->>API: updated state

    API-->>UI: SSE metadata event (turn info + question text)

    loop Sentence-by-sentence Streaming TTS
        API->>TTS: Synthesize sentence chunk (bulbul:v3 aayan)
        TTS-->>API: WAV audio bytes
        API-->>UI: SSE audio_chunk event (<800ms Time-to-First-Audio)
        UI->>User: Play sentence audio chunk immediately
    end
```

---

## 4. LangGraph interview phases

State machine for the four board phases.

```mermaid
stateDiagram-v2
    [*] --> daf_opening

    daf_opening --> subject_probe: pivot / quota met
    subject_probe --> current_affairs: pivot / quota met
    current_affairs --> closing: pivot / quota met
    closing --> [*]: interview_complete

    daf_opening --> daf_opening: follow-up
    subject_probe --> subject_probe: follow-up
    current_affairs --> current_affairs: follow-up
    closing --> closing: follow-up

    note right of daf_opening
        Questions from DAF profile only
    end note

    note right of subject_probe
        Syllabus hybrid RAG + optional subject
    end note

    note right of current_affairs
        Daily CA RAG + DAF anchor
        CA grounding score + retry
    end note
```

**Router actions** (`FollowUpRouterNode`):
- `probe` — vague or off-topic answer
- `daf_probe` — contradicts DAF profile
- `pivot` — clear answer, new angle
- `advance_phase` — phase exchange quota met

**Interview modes** (`config.py`):
- `quick`: 4 questions, 1 exchange per phase
- `full`: 12 questions, 3 exchanges per phase

---

## 5. Daily current affairs pipeline

How the `/current-affairs` page gets its content.

```mermaid
flowchart TD
    START([Startup or user opens Daily CA]) --> CACHE{Redis cache\n ca_bundle:DATE ?}

    CACHE -->|hit + live| RETURN[Return 10 enriched articles]
    CACHE -->|miss / stale| FETCH[NewsFetchTool.fetch_daily_upsc_bundle]

    FETCH --> P1[Politics query]
    FETCH --> P2[Economy query]
    FETCH --> P3[IR query]
    FETCH --> P4[Environment query]
    FETCH --> P5[Science / Ag / Security...]

    P1 --> MERGE[Merge + dedupe + score]
    P2 --> MERGE
    P3 --> MERGE
    P4 --> MERGE
    P5 --> MERGE

    MERGE --> PICK[Pick 10 diverse GS pillars]
    PICK --> ENRICH[NewsEnrichTool — Groq LLM]
    ENRICH --> STORE[Redis cache 24h]
    STORE --> INGEST[Chroma shared_ca_YYYY_MM_DD ingest]
    INGEST --> RETURN
    INGEST --> PREWARM[Background Hindi voice prewarm]

    FETCH -.->|API failure| FALLBACK[fallback_current_affairs.json]
    FALLBACK --> RETURN

    RETURN --> UI[Render cards + source links]

    UI --> LANG[User picks class language]
    LANG --> LISTEN{User clicks Listen?}
    LISTEN -->|yes| CACHED{Redis audio cache\n ca_explain_v15:DATE:lang:index ?}
    CACHED -->|hit| PLAY[VoicePlayer — instant]
    CACHED -->|miss| BRIEF[CaBriefingTool → localized script]
    BRIEF --> VALID[voice_is_valid + retry]
    VALID --> TTS[Sarvam TTS bulbul:v3 aayan]
    TTS --> SAVE[Redis cache audio]
    SAVE --> PLAY
    TTS -.->|402 / fail| BROWSER[Browser TTS fallback]
```

---

## 6. Multilingual voice briefing pipeline

Teacher-style classroom voice for daily CA (separate from interview question voice).

```mermaid
flowchart LR
    ART[EnrichedArticle] --> PROMPT[Language-specific prompt\nAayan persona]
    PROMPT --> LLM[Groq LLM]
    LLM --> VALID{Script validation}
    VALID -->|fail| RETRY[Retry with stricter rules]
    RETRY --> LLM
    VALID -->|pass| TTS[Sarvam TTS\nlang-specific code]
    TTS --> REDIS[(Redis\nca_explain_v15:\nDATE:lang:index)]
    TTS -.->|fail| NO_CACHE[Return briefing_voice\nfor browser TTS]
```

**Supported languages** (`app/config/ca_languages.py`):

| Code | Language | Sarvam TTS |
|------|----------|------------|
| `hi` | Hindi | `hi-IN` |
| `en` | English | `en-IN` |
| `bn` | Bengali | `bn-IN` |
| `ta` | Tamil | `ta-IN` |
| `te` | Telugu | `te-IN` |
| `mr` | Marathi | `mr-IN` |
| `kn` | Kannada | `kn-IN` |
| `gu` | Gujarati | `gu-IN` |
| `ml` | Malayalam | `ml-IN` |
| `pa` | Punjabi | `pa-IN` |
| `od` | Odia | `od-IN` |

**Prompt rules (all Indic languages):**
- Do not read English headline — hook question first
- Native script only; no Roman letters
- Translate English concepts to local words (not phonetic transliteration)
- 180–220 words; structure: hook → facts → India impact → UPSC angle → recap
- Screen JSON fields (`prelims_pointer`, `mains_angle`, etc.) stay English

---

## 7. RAG data model

What gets embedded and retrieved.

```mermaid
erDiagram
  SHARED_SYLLABUS ||--o{ CHUNK : contains
  SHARED_CA ||--o{ CHUNK : contains

  SHARED_SYLLABUS {
    string collection "shared_syllabus"
    string source "sample_syllabus.txt"
  }

  SHARED_CA {
    string collection "shared_ca_YYYY_MM_DD"
    string source "daily Redis bundle"
    date edition_date
  }

  CHUNK {
    string text
    string doc_type "syllabus | current_affairs"
    string source_title
  }

  SESSION {
    uuid session_id
    json daf_profile
    list ca_articles
    string current_phase
  }
```

| Collection | Scope | Used in |
|------------|-------|---------|
| `shared_syllabus` | Global, content-hash cached at startup | Subject probe phase |
| `shared_ca_{YYYY_MM_DD}` | Daily bundle, shared across users | Current affairs phase |
| Redis `ca_bundle:{date}` | 10 enriched articles, 24h TTL | Daily CA page |
| Redis `ca_explain_v15:{bundle}:{lang}:{index}` | Briefing + audio per language | Listen / play-all |
| Redis session | Per interview, 1h TTL | All interview phases |

**Retrieval:** hybrid fusion — Chroma vector search + BM25 (`app/rag/retriever.py`).

---

## 8. DAF upload → prefetch

Background work triggered on upload.

```mermaid
sequenceDiagram
    participant UI
    participant API
    participant DAF as DafTool
    participant CA as CA pipeline
    participant Redis

    UI->>API: POST /upload-daf (PDF)
    API->>DAF: pdfplumber + Groq profile extract
    DAF-->>API: DAFProfile
    API->>Redis: Save session state
    API-->>UI: session_id

    Note over API,CA: Background task
    API->>CA: _prefetch_ca_background
    CA->>Redis: get/set ca_bundle
    CA->>CA: ingest_shared_current_affairs
```

On **app startup**, if today's bundle is already cached, Hindi voice prewarm runs automatically in background.

---

## 9. Frontend routes

```mermaid
flowchart LR
    ROOT["/"] --> UPLOAD[DAF upload + mode picker]
    UPLOAD -->|session_id| INT["/interview"]
    INT -->|complete| FB["/feedback"]
    ROOT --> CA["/current-affairs"]
    CA --> LANG[Language selector\nlocalStorage]
    CA --> LISTEN[Listen / Play full edition]
    LISTEN --> EXPLAIN[POST /explain?language=]
    EXPLAIN --> CARD[CaBriefingCard + VoicePlayer]

    INT -.->|dev=1| TEXT[Text answer fallback]
    EXPLAIN -.->|no Sarvam audio| BROWSER[BrowserVoicePlayer]
```

**CA page features:**
- Class language dropdown (11 languages, persisted in `localStorage`)
- Per-story Read + Listen
- Play full edition playlist with study progress + streak
- Sarvam WAV playback primary; Web Speech API fallback

---

## 10. Key design decisions

| Decision | Rationale |
|----------|-----------|
| **LangGraph** for interview | Explicit phases + router; traceable, extensible state machine |
| **Shared daily CA cache** | One enrich pass per day, not per user |
| **Per-language voice cache** | Tamil student gets Tamil audio without re-running Hindi |
| **Hindi auto-prewarm** | Default language ready on startup; others on-demand |
| **Aayan teacher persona** | Conversational UPSC faculty, not headline reader |
| **Script validation** | Reject LLM output with wrong script / Roman in Indic |
| **No cache on TTS failure** | Avoid locking empty audio; browser TTS still works |
| **Hybrid RAG** | BM25 + vectors improves syllabus keyword match |
| **Sarvam for voice** | Indian accent, 11 languages, codemix STT |
| **NewsData not scrape** | Legal, stable API; portfolio-safe |
| **Langfuse tracing** | Debug LLM/voice/RAG pipelines in development |
| **Groq cooldown guard** | Respect 429 retry-after; skip wasted retries |
| **Redis session TTL** | Simple multi-user demo without auth |

---

## 11. Environment variables

```mermaid
flowchart TB
    ENV[".env configuration"]

    subgraph REQ["Required"]
        direction TB
        R1["GROQ_API_KEY"]
        R2["GROQ_MODEL"]
        R3["SARVAM_API_KEY"]
        R4["NEWSDATA_API_KEY"]
    end

    subgraph VOICE["Voice tuning"]
        direction TB
        V1["SARVAM_TTS_SPEAKER=aayan"]
        V2["SARVAM_TTS_PACE=0.93"]
        V3["SARVAM_STT_MODE=codemix"]
    end

    subgraph INFRA["Infrastructure"]
        direction TB
        I1["REDIS_URL"]
        I2["CHROMA_PATH"]
    end

    subgraph OPT["Optional"]
        direction TB
        O1["LANGFUSE_PUBLIC_KEY"]
        O2["LANGFUSE_SECRET_KEY"]
        O3["DAILY_CA_ARTICLE_COUNT"]
        O4["INTERVIEW_MODE=full|quick"]
    end

    ENV --> REQ
    ENV --> VOICE
    ENV --> INFRA
    ENV --> OPT
```

---

## 12. API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health + `ca_preparing` |
| `POST` | `/upload-daf` | PDF → DAFProfile + CA prefetch |
| `POST` | `/start-interview` | First question + TTS |
| `POST` | `/respond` | STT → graph turn → TTS |
| `GET` | `/feedback-report/{id}` | Rubric report |
| `GET` | `/metrics/{id}` | Step latency metrics |
| `GET` | `/current-affairs/daily` | Today's CA list |
| `GET` | `/current-affairs/languages` | Voice language registry |
| `POST` | `/current-affairs/explain` | Briefing + audio (`language` form field) |
| `GET` | `/current-affairs/prewarm-status` | Audio readiness |
| `POST` | `/current-affairs/prewarm` | Manual voice prewarm |

---

## 13. Quality & fallback patterns

| Failure | Handling |
|---------|----------|
| Groq 429 | Cooldown via `groq_guard.py`; Hindi/static fallbacks |
| Groq model 404 | No retry; fallback briefing |
| Sarvam 402 / TTS error | `voice_error` message; browser TTS; **not cached** |
| NewsData 429 | Exponential backoff; static fallback JSON |
| Redis down | In-memory fallback in `SessionStore` + `CaCache` |
| LLM JSON parse fail | Fence strip + bracket repair; extract `briefing_voice` regex |
| CA grounding low | Retry question generation with `CA_RETRY_SUFFIX` |
| Briefing script invalid | 2-attempt retry with language-specific correction prompt |

---

## 14. Latency (typical)

| Operation | Cold | Warm |
|-----------|------|------|
| Daily CA first enrich | 30–60s | <1s cached bundle |
| Hindi voice prewarm (10 stories) | ~1–2 min background | instant Listen |
| Other language first Listen | ~10–15s (LLM + TTS) | instant from Redis |
| Start interview | 15–25s | 5–8s if prefetch done |
| Per voice interview turn | 4–8s | STT + 2× LLM + TTS |

---

## 15. Future extensions (out of scope)

These are intentionally **not** implemented — listed for portfolio discussion only:

- User accounts and long-term progress history
- Formal eval suite / A/B benchmarking for voice quality
- MCQ practice per daily edition
- Date archive UI
- Admin CMS for manual CA curation
- Voice model fine-tuning
- Horizontal scale / managed vector DB
- Prewarm all 11 languages on startup (cost vs. demand tradeoff)

---

*Last updated: September 2026 — multilingual CA voice classroom, Redis voice prewarm, Aayan Sarvam TTS, LangGraph interview agent.*
