# Local RAG Studio

A small app for **learning how RAG (retrieval-augmented generation) works by watching it run**.

Upload your documents, ask questions, and get answers with citations. Then switch on
**Lab mode** to see every step the pipeline took: how the text was split into chunks,
which chunks were retrieved and how close each one was, the exact prompt sent to the
LLM, and how long each stage took.

The backend is FastAPI, the frontend is React, and everything runs on your own machine.
Embeddings and the vector index are local. The LLM can be any OpenAI-compatible
endpoint: a hosted one such as OpenRouter, or a fully local one such as Ollama.

## What you can do with it

- **Build knowledge bases** from PDF, DOCX, Markdown and text files, or from web page URLs.
- **Chat with your documents.** Answers cite their sources as `file, page N`.
- **Watch indexing live**: loading, splitting, embedding and indexing, with stats and sample chunks.
- **Inspect any answer** (Lab mode):
  - the search query, including how a follow-up question was rewritten
  - the retrieved chunks with their distances and ranks
  - the exact prompt the LLM received
  - a timing breakdown of every stage
- **See your documents as a vector map**: every chunk drawn as a dot (a 2D PCA
  projection), with your question and the chunks it retrieved highlighted.
- **Experiment with the settings** and compare results: chunk size, overlap,
  number of chunks (k), minimum relevance, hybrid search (vectors + BM25 keywords),
  a cross-encoder reranker, query rewriting and heading-aware chunking.

## How it works

```
Indexing (once per document)          Answering (every question)

  1. LOAD    file -> text per page      (rewrite the follow-up question)
  2. SPLIT   pages -> chunks            5. RETRIEVE  question -> best k chunks
  3. EMBED   chunk -> vector            6. PROMPT    question + chunks -> prompt
  4. INDEX   vectors -> Chroma          7. GENERATE  LLM streams the answer
```

Each step is one file in [backend/app/rag/](backend/app/rag/), written to be read:
every module starts by explaining *why* its step exists and what its settings
trade off. The steps are plain function calls, not a framework chain, so you can
put a breakpoint anywhere and look at what flows to the next step.

Start with [docs/rag-explained.md](docs/rag-explained.md). It walks through the
pipeline and suggests five experiments to try in Lab mode.

## Requirements

- Python 3.11 or newer
- Node.js 20.19 or newer (22 LTS or later recommended)
- An LLM endpoint: an [OpenRouter](https://openrouter.ai) API key, or
  [Ollama](https://ollama.com) running locally

## Setup

Run these from the project folder.

**1. Install the dependencies**

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
cd frontend; npm install; cd ..
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm install)
```

On Linux, `pip` installs the CUDA build of PyTorch by default, which is several GB.
For a CPU-only install, add `--extra-index-url https://download.pytorch.org/whl/cpu`
to the `pip install` command.

**2. Configure the LLM**

Copy `.env.example` to `.env`, then set your key and model in it:

```ini
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-your-key-here
LLM_MODEL=your-provider/your-model
```

To run fully locally with Ollama, run `ollama pull llama3.2` and use these instead:

```ini
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2
```

`.env.example` lists every option.

**3. Set the admin password**

Changing settings in the app asks for this password. The command stores only a
hash of it (plus a signing secret) in `.env`.

```powershell
# Windows
cd backend; ..\.venv\Scripts\python -m app.scripts.set_admin_password; cd ..
```

```bash
# macOS / Linux
(cd backend && ../.venv/bin/python -m app.scripts.set_admin_password)
```

## Run

| | |
|---|---|
| Windows | `powershell -ExecutionPolicy Bypass -File .\run.ps1` |
| macOS / Linux | `./run.sh` |

This starts both parts. Press Ctrl+C to stop them.

- App: http://127.0.0.1:5173
- API: http://127.0.0.1:8000 (interactive docs at http://127.0.0.1:8000/docs)

To start the two parts by hand, use two terminals:

```powershell
cd backend; ..\.venv\Scripts\python -m app      # macOS/Linux: ../.venv/bin/python -m app
cd frontend; npm run dev
```

The first start is slow, because the embedding model (about 90 MB) is downloaded once.

## Tests

The backend tests run offline, using a fake LLM and fake embeddings:

```powershell
cd backend; ..\.venv\Scripts\python -m pytest    # macOS/Linux: ../.venv/bin/python -m pytest
```

For the frontend, `npm run typecheck` and `npm run build` (in `frontend/`) check the types and the build.

## Project layout

```
backend/app/
  rag/        the RAG pipeline, one step per file (start here)
  api/        HTTP endpoints
  jobs/       background ingest and re-index jobs, with live progress
  ...         config, storage, auth, LLM client, upload and URL safety checks
backend/tests/  offline test suite
frontend/src/   React + TypeScript + Tailwind UI
docs/           how the pipeline works, the architecture, design notes
data/           created at runtime: your knowledge bases and settings (not in git)
```

More detail:

- [docs/rag-explained.md](docs/rag-explained.md): the pipeline step by step, and experiments to try
- [docs/architecture.md](docs/architecture.md): folder structure, API and event formats
- [docs/decisions.md](docs/decisions.md): design choices and known limits

## Privacy and security

- Your files, their embeddings and the index stay on your machine, in `data/`.
- With a hosted LLM, the retrieved chunks and your question are sent to that
  provider with each request. With Ollama, nothing leaves your machine.
- The server listens on `127.0.0.1` only and is built for a single local user.
  Do not expose it to a network as it is: only settings changes are password-protected.

## Troubleshooting

- **Red LLM dot in the sidebar:** the model name or key is wrong. Click the dot
  for the exact error, fix `.env`, then restart the backend.
- **"Stale index":** the chunk settings changed since the knowledge base was
  indexed. Click **Re-index now**.
- **Changes to `.env` have no effect:** the config is read once at startup, so restart the backend.
- **A scanned PDF reports "no text could be extracted":** it contains images, not text. OCR is not supported.

## Acknowledgements

Built with [FastAPI](https://fastapi.tiangolo.com), [LangChain](https://www.langchain.com),
[Chroma](https://www.trychroma.com), [sentence-transformers](https://www.sbert.net),
[React](https://react.dev) and [Tailwind CSS](https://tailwindcss.com).
Several ideas, such as storing extracted text for fast re-indexing and skipping
the LLM when nothing relevant is found, were inspired by studying
[AnythingLLM](https://github.com/Mintplex-Labs/anything-llm).
