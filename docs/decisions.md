# Design notes

Short notes on the choices behind the app, and on what it deliberately leaves out.

## Structure
- **Flat modules where a package would hold one file.** `config.py`,
  `schemas.py`, `llm.py`, `auth.py`, `storage.py`, `sources.py` and
  `state.py` are single modules. `rag/`, `jobs/`, `api/` and `scripts/` are
  packages.
- **`python -m app` starts the server** on 127.0.0.1:8000 (from `HOST` and
  `PORT`). This keeps the start command short and loopback-only by default.
- The **virtual environment lives in `.venv/`** at the project root.
- **Keep the project outside OneDrive** (or any synced folder). Syncing
  `.venv/` and `node_modules/` is slow, and sync and editor processes can lock
  `python.exe`, which breaks `python -m venv`.

## RAG behaviour
- **Plain function calls, not chains.** The pipeline calls each step
  explicitly instead of composing a LangChain chain, so every intermediate
  value can be inspected, in a debugger and in the UI.
- **Chunk sizes are in characters**, matching LangChain's splitter.
- **Pages vs sections.** PDFs keep real page numbers. DOCX has no fixed pages,
  so DOCX, Markdown and web pages are split at their headings into "section
  N: Heading". A `.txt` file is a single section.
- **Cosine distance.** Chroma collections use cosine distance (0 = identical).
  The UI's "relevance" bar is `1 − distance`, clipped to 0..1. The raw
  distance is always shown too.
- **Minimum relevance.** The `min_relevance` setting drops chunks whose
  relevance is below it, so `k` is a maximum, not a guarantee. 0 turns it off.
- **Extracted text is stored.** Each source's text is saved as JSON when it
  is loaded, so a re-index never re-downloads or re-parses anything.
- **Adding sources to an existing collection** chunks them with that
  collection's *recorded* settings, so one index never mixes two chunkings.
  New settings apply on re-index.
- **Stale, not silently rebuilt.** Each collection records the settings its
  index was built with. When they differ from the current settings, the
  collection is marked stale and the user chooses when to re-index.
- **Re-index without downtime.** Each re-index builds a new Chroma collection
  (`chunks_v2`, `chunks_v3`, ...), switches the manifest over, and then drops
  the old version. Chat keeps working during a re-index, and a failed
  re-index leaves the old index untouched.
- **The embedding model counts as an index setting.** Changing
  `EMBEDDING_MODEL_NAME` makes collections stale *and* blocks chat on them
  (409) until they are re-indexed, because vectors from different models
  cannot be compared.
- **Query rewriting** runs only when there is history. Search uses the
  rewritten query, but the final prompt keeps the user's original question
  together with the last 6 messages (1,500 characters each).
- **Event order is pipeline order.** `rewrite` (when it runs) comes before
  `sources`, and both come before any answer tokens.
- **No context, no LLM call.** If retrieval returns nothing (an empty index,
  or nothing above the minimum relevance), the answer is a fixed "I don't
  know" and the LLM is not called.
- **Hybrid search** uses BM25 with no stemming, and only a small stop-word
  list. It is merged with RRF (k = 60) over a pool of `max(4k, 20)`.
  Chunks found only by keywords get their real cosine distance computed for
  display.
- **Reranker:** `cross-encoder/ms-marco-MiniLM-L-6-v2`, applied to the same
  pool. It starts downloading in the background when enabled. If it cannot
  load, chat answers without it and shows a notice.
- **Heading detection for PDFs** is a heuristic: Markdown `#`, numbered lines
  (`2.1 Storage Accounts`) and short ALL-CAPS lines. Very short sections are
  merged into the next one.
- **The vector map uses PCA**, not t-SNE or UMAP. PCA is a fixed linear
  formula, so a new question can be placed on an existing map exactly.
- **Models load from the local Hugging Face cache first**, so restarts work
  offline. The network is used only for the first download.

## API and security
- **Only `PUT /settings` needs the admin token.** Creating, re-indexing and
  deleting collections is open, because the server binds to 127.0.0.1 for a
  single local user. Adding `Depends(require_admin)` to those routes would
  lock them too.
- **The login rate limit counts every attempt**: 5 per minute per IP, kept in
  memory, with a `Retry-After` header. Argon2 verification is constant-time.
  A dummy hash is checked when no password is set, so timing does not reveal
  that.
- **After running `set_admin_password`, restart the backend.** Config is read
  once at startup. Login returns a clear 503 until a password exists.
- **SSRF defence.** Only http/https URLs are accepted. Every DNS answer must
  be a public IP. `localhost`, `*.local` and `*.internal` are refused by
  name. The connection goes to the *validated IP* (with Host header and SNI
  set), which defeats DNS rebinding. Each redirect is re-validated (at most 5).
  Limits are a 15 MB body, a 20 s timeout, and a content-type allowlist.
- **Uploads:** 25 MB per file, at most 20 sources per request, an extension
  allowlist plus a file-signature check (`%PDF-`, the ZIP header for DOCX, no
  NUL bytes in text). Files are stored as `<uuid>.<ext>`, and the cleaned
  original name is used only for display.
- **Secrets.** The key and hashes are `SecretStr`. Every log line goes
  through a redacting formatter, and provider error messages are redacted
  before they are returned. The admin token lives only in React memory,
  never in `localStorage`.
- **Ollama needs no real key.** For localhost base URLs, a placeholder key is
  used when `LLM_API_KEY` is empty.

## Runtime state
- **Jobs are kept in memory.** One worker thread runs jobs in order. Job
  history is lost on restart, but indexes are not.
- **Chat history is kept in the browser**, in `localStorage`, per collection
  (the last 100 messages each). It is not stored on the server.

## Not included
- OCR for scanned PDFs (they report "no text could be extracted").
- Multiple users, per-user auth, and server-side chat history.
- Token-accurate chunking. Sizes are characters, and the Inspector's token
  count is an estimate (characters ÷ 4).
- Automated UI tests. Frontend correctness relies on TypeScript's strict mode
  and the production build.
