# Architecture

Local RAG Studio is a FastAPI backend (Python) plus a React/Vite frontend.
All RAG logic lives in `backend/app/rag/`. Everything else is plumbing.

## Folder structure

```
backend/app/
  __main__.py        `python -m app` starts uvicorn on 127.0.0.1:8000
  main.py            FastAPI app factory: CORS, error handlers, routers, startup
  config.py          pydantic-settings: reads <project root>/.env (single config source)
  state.py           AppContext: stores, open indexes, model loaders (tests inject fakes here)
  errors.py          consistent error format, secret redaction for responses and logs
  schemas.py         pydantic request/response/settings models
  rag/               THE PIPELINE (commented for learning)
    loading.py       file -> per-page/section text
    chunking.py      pages -> chunks (recursive, optional heading-aware)
    embedding.py     local sentence-transformers model, batched embedding
    vectorstore.py   persistent Chroma index per collection
    retrieval.py     vector search, BM25 hybrid (RRF), cross-encoder rerank
    prompting.py     system prompt, context block, query-rewrite prompt
    generation.py    query rewrite + streamed answer
    pipeline.py      the two flows as explicit steps: build_index(), answer()
    projection.py    2D PCA projection for the vector map
  llm.py             OpenAI-compatible chat client factory + /health/llm check
  sources.py         upload validation, SSRF-safe URL fetching
  storage.py         collections (manifest.json, raw text), settings.json
  jobs/
    manager.py       job queue (one worker) + event log for SSE
    ingest.py        the ingest and re-index jobs
  auth.py            argon2 verify, JWT, login rate limiter, require_admin
  api/               routers: health, auth, settings, collections, ingest, chat
  scripts/set_admin_password.py
backend/tests/       pytest (fake LLM + hashing embeddings: offline, fast)
frontend/src/        React + TypeScript + Tailwind
  lib/               REST client, SSE reader, shared types
  hooks/             data hooks and chat state
  components/        the UI
data/                runtime data (git-ignored)
  settings.json
  collections/<id>/manifest.json
  collections/<id>/raw/<source_id>.json      extracted text, per page/section
  collections/<id>/uploads/<generated>.<ext> original uploads
  collections/<id>/chroma/                   persistent vector index
```

In the code and the API, a knowledge base is called a *collection*.

## Configuration

`.env` in the project root, read by pydantic-settings. Real environment
variables override it. `LLM_API_KEY` falls back to `OPENROUTER_API_KEY`.
The config is read once at startup, so restart the backend after changing it.

## API contract

All JSON. Errors always use this shape:
`{"error": {"code": "snake_case", "message": "Human-readable text", "details": any}}`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | - | liveness |
| GET | `/health/llm?refresh=bool` | - | checks model list + tiny completion; cached 60 s |
| POST | `/auth/login` | - | `{password}` -> `{token, expires_in}`; 5 attempts/min/IP |
| GET | `/settings` | - | current RAG settings + reranker status |
| PUT | `/settings` | Bearer | update settings (validated bounds) |
| GET | `/collections` | - | list with `stale`, `stale_reasons` |
| POST | `/collections` | - | multipart: `name`, `files[]`, `urls[]` -> `{collection, job}` |
| GET | `/collections/{id}` | - | detail incl. sources |
| DELETE | `/collections/{id}` | - | delete collection and its data |
| POST | `/collections/{id}/sources` | - | multipart: `files[]`, `urls[]` -> `{collection, job}` |
| POST | `/collections/{id}/reindex` | - | re-chunk from stored raw text -> `{collection, job}` |
| GET | `/collections/{id}/map` | - | every chunk as a 2D point (PCA) for the vector map |
| GET | `/collections/{id}/map/query?q=` | - | where a question lands on that same map |
| GET | `/ingest/jobs/{job_id}` | - | latest job snapshot |
| GET | `/ingest/jobs/{job_id}/events` | - | SSE progress stream |
| POST | `/chat` | - | SSE answer stream |

Only settings changes need the admin token. Collection operations are open
because the server binds to 127.0.0.1 and serves one user (see `decisions.md`).

## SSE

Format: `event: <type>\ndata: <json>\n\n`. The job stream sends `: keep-alive`
comments every 15 s.

### Ingest/re-index job events (`GET /ingest/jobs/{id}/events`)

Every event is a full snapshot (`event: progress`), so the client only needs
to keep the latest one. Earlier events are replayed when a client connects.

```jsonc
{
  "seq": 7, "job_id": "…", "kind": "ingest|reindex", "collection_id": "…",
  "stage": "queued|loading|splitting|embedding|indexing|done|error",
  "message": "Embedding batch 3/5",
  "elapsed_s": 4.21,
  "stats": { "pages": 12, "characters": 34120, "chunks": 41,
             "embedded": 32, "embedding_pct": 78.0, "indexed": 0 },
  "sources": [ { "source_id": "…", "name": "notes.pdf", "kind": "file|url",
                 "status": "pending|loading|loaded|indexed|error",
                 "pages": 12, "characters": 34120, "chunks": 41, "error": null } ],
  "sample_chunks": [ { "chunk_id": 0, "source_name": "notes.pdf",
                       "location": "page 1", "chars": 1480, "text": "first 200 chars…" } ],
  "error": null
}
```
The stream closes after `stage` is `done` or `error`. Per-source failures set
that source's `status: "error"` and the other sources continue.

### Chat events (`POST /chat`)

Request: `{"collection_id": "…", "question": "…", "history": [{"role": "user|assistant", "content": "…"}]}`

The events are sent in pipeline order:

| event | data |
|---|---|
| `notice` | `{message}`, for example "Reranker unavailable, answering without it" |
| `rewrite` | `{original, rewritten, ms}` (only when query rewriting runs) |
| `sources` | `{query, mode, dropped, chunks: [{rank, chunk_id, source_id, source_name, location, page, heading, distance, relevance, vector_rank, bm25_rank, rerank_score, hybrid_score, rerank_relevance, chars, snippet, text}]}` |
| `prompt` | `{messages: [{role, content}], text}`: the exact prompt sent to the LLM |
| `token` | `{text}` |
| `timings` | `{rewrite_ms, embed_ms, search_ms, bm25_ms, rerank_ms, retrieval_ms, ttft_ms, generation_ms, total_ms}` |
| `done` | `{answer, finish_reason}` |
| `error` | `{code, message, hint}` |

`distance` is cosine distance (0 = identical, 2 = opposite) and `relevance`
is `1 − distance`, clipped to 0..1. `dropped` counts the candidates removed by
the `min_relevance` setting. Retrieval runs exactly once per question, and the
same chunk list feeds both `sources` and `prompt`. If the client disconnects,
generation stops.
