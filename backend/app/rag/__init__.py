"""
The RAG pipeline: everything that turns documents into answers lives here.

Read the files in this order. Each one is a single step:

    loading.py      1. LOAD      file -> plain text, one record per page/section
    chunking.py     2. SPLIT     pages -> overlapping chunks small enough to search
    embedding.py    3. EMBED     chunk text -> vector (a list of numbers = "meaning")
    vectorstore.py  4. INDEX     store vectors on disk (Chroma) so we can search them
    retrieval.py    5. RETRIEVE  question -> the k most relevant chunks
    prompting.py    6. PROMPT    question + chunks -> the exact text the LLM reads
    generation.py   7. GENERATE  ask the LLM, stream the answer back
    pipeline.py     The two flows, written as plain explicit steps:
                      build_index()  steps 2-4 (step 1 runs per source first)
                      answer()       steps 5-7 (plus optional query rewriting)
    projection.py   Bonus: flatten the vectors to 2D (PCA) for Lab mode's vector map

Nothing in this package knows about HTTP, auth, or the UI. Everything else
in the backend is plumbing around these functions.
"""
