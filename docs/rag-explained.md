# How RAG works in this app

RAG (retrieval-augmented generation) means the LLM answers from a few passages
of your documents that we look up first. It does not answer from memory. All
the code for this lives in `backend/app/rag/`, one file per step.

## The pipeline

**Indexing** runs once per document (and again when you re-index).
`pipeline.build_index()` runs steps 2-4. `jobs/ingest.py` runs step 1 for each
source in the background.

| Step | File | What happens | Why |
|---|---|---|---|
| 1. Load | `rag/loading.py` | File becomes text, one record per PDF page or per section (DOCX, Markdown, web page). Saved as JSON in `data/collections/<id>/raw/`. | Page numbers survive, so citations can say "file X, page N". A re-index skips this step. |
| 2. Split | `rag/chunking.py` | Pages are cut into chunks of at most `chunk_size` characters, repeating `chunk_overlap` characters between neighbours. Heading-aware mode cuts at headings first. | One vector per chunk. Small chunks give sharp matches. Overlap keeps sentences whole across a cut. |
| 3. Embed | `rag/embedding.py` | A local model (all-MiniLM-L6-v2) turns each chunk into 384 numbers. | Similar meaning gives nearby vectors, so we can search by meaning, not keywords. |
| 4. Index | `rag/vectorstore.py` | Vectors and text are written to Chroma on disk. | Restarting reloads the index. Nothing is re-embedded. |

**Answering** runs for every question. `pipeline.answer()` runs these steps
and streams each result to the Pipeline Inspector.

| Step | File | What happens |
|---|---|---|
| (Rewrite) | `rag/generation.py` | If there is chat history, a small LLM call turns "and how much is it?" into a standalone question. That question is used for the search. |
| 5. Retrieve | `rag/retrieval.py` | The question is embedded with the same model, and the `k` nearest chunks are found. Optionally BM25 keyword search is merged in (RRF), and a cross-encoder re-orders the results. This runs **once**. The same chunks feed both the sources list and the prompt. |
| 6. Prompt | `rag/prompting.py` | A strict system prompt ("only from context, else say you don't know") plus the numbered chunks `[1] file, page N`, recent history and your question. |
| 7. Generate | `rag/generation.py` | The prompt goes to the OpenAI-compatible LLM (OpenRouter or Ollama), and tokens stream back. |

**Reading distances.** Distances are cosine distances: 0 means identical
meaning. With MiniLM, below about 0.5 is a strong match, 0.5-0.8 is related,
and above about 0.9 is unrelated. The Inspector's distance strip shows where
each retrieved chunk sits on that scale.

## Five experiments

Open **Lab mode** in a chat, ask the same question before and after each
change, and compare. Chunk settings need **Save → Re-index**. The other
settings apply to the next question.

1. **Chunk size 500 vs 3000** (re-index). Look at *Sample chunks* in the
   pipeline view and the chunk count. In the Inspector, 500 gives tighter
   distances on narrow fact questions but each chunk carries little context.
   3000 gives fewer, blurrier chunks whose distances bunch together, and the
   prompt's ≈token count grows a lot.
2. **k = 2 vs 10** (instant). At 2, check whether the answer misses facts that
   sit in chunk #3 or #4. At 10, look at the distance strip: the extra chunks
   are usually far away (above 0.8). They are noise that costs tokens (see the
   prompt size).
3. **Overlap 0 vs 300** (re-index). Compare chunk counts (more overlap gives
   more chunks). Ask about a fact that falls on a chunk boundary. With 0, the
   sentence may be cut in half across two chunks. With 300, expand
   neighbouring chunks in the Inspector and you will see the repeated text.
4. **Hybrid search on/off** (instant). Ask with an exact term: a code, a name,
   a number. The Inspector shows a `bm25 #` next to `vector #`, and chunks
   found only by keywords have no vector rank. BM25 matches exact words only
   ("ticket" does not match "tickets"), which is why it complements vectors
   instead of replacing them.
5. **Reranker on/off** (instant; the first use downloads about 90 MB).
   Compare `rerank` scores with `vector #`. When the cross-encoder disagrees
   with the embedding ranking, read both chunks and judge which is really
   more relevant. *Timings* shows what the extra accuracy costs (`rerank`
   ms).
