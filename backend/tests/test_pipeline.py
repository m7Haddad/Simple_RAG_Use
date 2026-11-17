import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rag import pipeline
from app.rag.vectorstore import VectorIndex

from .conftest import FAKE_ANSWER
from .helpers import parse_sse, wait_for_job


def _chat(client, collection_id, question, history=None):
    response = client.post("/chat", json={"collection_id": collection_id, "question": question, "history": history or []})
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


@pytest.fixture
def count_retrievals(monkeypatch):
    calls = {"retrieve": 0, "search": 0}
    real_retrieve, real_search = pipeline.retrieve, VectorIndex.search

    def counting_retrieve(*args, **kwargs):
        calls["retrieve"] += 1
        return real_retrieve(*args, **kwargs)

    def counting_search(self, *args, **kwargs):
        calls["search"] += 1
        return real_search(self, *args, **kwargs)

    monkeypatch.setattr(pipeline, "retrieve", counting_retrieve)
    monkeypatch.setattr(VectorIndex, "search", counting_search)
    return calls


def test_ingest_keeps_page_numbers(indexed_collection):
    sources = {s["name"]: s for s in indexed_collection["sources"]}
    assert sources["azure-notes.pdf"]["pages"] == 2
    assert indexed_collection["chunk_count"] == 3
    assert indexed_collection["indexed_with"]["chunk_size"] == 1500


def test_ingest_sse_stream_reports_stages(client):
    response = client.post("/collections", data={"name": "Stream"}, files=[("files", ("a.txt", b"Alpha beta gamma. " * 50, "text/plain"))])
    job_id = response.json()["job"]["job_id"]
    with client.stream("GET", f"/ingest/jobs/{job_id}/events") as stream:
        body = "".join(stream.iter_text())
    events = [json.loads(data) for name, data in parse_sse(body) if name == "progress"]
    stages = [e["stage"] for e in events]
    for stage in ("loading", "splitting", "embedding", "indexing", "done"):
        assert stage in stages
    final = events[-1]
    assert final["stats"]["embedding_pct"] == 100.0
    assert final["stats"]["chunks"] >= 1 and final["stats"]["characters"] > 0
    assert final["sample_chunks"] and len(final["sample_chunks"][0]["text"]) <= 200
    assert final["sources"][0]["status"] == "indexed"


def test_chat_streams_sources_prompt_tokens_in_order(client, indexed_collection, count_retrievals):
    events = _chat(client, indexed_collection["id"], "What does blob storage keep?")
    names = [name for name, _ in events]
    assert names[0] == "sources"
    assert names.index("prompt") < names.index("token") < names.index("timings") < names.index("done")
    assert count_retrievals == {"retrieve": 1, "search": 1}

    sources = json.loads(events[0][1])
    top = sources["chunks"][0]
    assert top["source_name"] == "azure-notes.pdf" and top["page"] == 1 and top["location"] == "page 1"
    assert 0 <= top["distance"] <= 2
    distances = [c["distance"] for c in sources["chunks"]]
    assert distances == sorted(distances), "chunks must be ranked closest first"

    prompt = json.loads(dict(events)["prompt"])
    assert "[1] azure-notes.pdf, page 1" in prompt["text"]
    for chunk in sources["chunks"]:
        assert chunk["text"].strip() in prompt["text"], "the prompt must use exactly the retrieved chunks"
    assert "say you don't know" in prompt["messages"][0]["content"]

    answer = "".join(json.loads(data)["text"] for name, data in events if name == "token")
    assert answer == FAKE_ANSWER
    timings = json.loads(dict(events)["timings"])
    assert {"retrieval_ms", "ttft_ms", "total_ms"} <= set(timings)


def test_second_page_cited_correctly(client, indexed_collection):
    events = _chat(client, indexed_collection["id"], "How do network security groups filter traffic in a virtual network?")
    top = json.loads(events[0][1])["chunks"][0]
    assert (top["source_name"], top["page"]) == ("azure-notes.pdf", 2)


@pytest.mark.parametrize("llm_responses", [["What are the access tiers of blob storage?", FAKE_ANSWER]])
def test_query_rewrite_then_single_retrieval(client, indexed_collection, count_retrievals, admin_token, llm_responses):
    history = [{"role": "user", "content": "Tell me about blob storage"}, {"role": "assistant", "content": "It stores blobs [1]."}]
    events = _chat(client, indexed_collection["id"], "what tiers does it have?", history)
    names = [n for n, _ in events]
    assert names[0] == "rewrite" and names[1] == "sources"
    rewrite = json.loads(events[0][1])
    assert rewrite["rewritten"] == "What are the access tiers of blob storage?"
    assert json.loads(events[1][1])["query"] == rewrite["rewritten"]
    assert count_retrievals["retrieve"] == 1 and count_retrievals["search"] == 1


def test_hybrid_and_rerank_still_retrieve_once(client, indexed_collection, admin_token, count_retrievals):
    settings = client.get("/settings").json()["settings"]
    settings.update(hybrid_search=True, reranker=True, query_rewrite=False)
    assert client.put("/settings", json=settings, headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
    events = _chat(client, indexed_collection["id"], "archive tier cheapest")
    sources = json.loads(dict(events)["sources"])
    assert sources["mode"] == "hybrid+rerank"
    assert sources["chunks"][0]["source_name"] == "extra.md"
    assert sources["chunks"][0]["rerank_score"] is not None
    for chunk in sources["chunks"]:
        assert 0 <= chunk["hybrid_score"] <= 1 and 0 <= chunk["rerank_relevance"] <= 1
    assert all(c["distance"] is not None for c in sources["chunks"])
    assert count_retrievals == {"retrieve": 1, "search": 1}


def test_min_relevance_drops_far_chunks_and_skips_llm(client, indexed_collection, admin_token):
    settings = client.get("/settings").json()["settings"]
    settings.update(min_relevance=0.9, query_rewrite=False)
    assert client.put("/settings", json=settings, headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
    events = dict(_chat(client, indexed_collection["id"], "completely unrelated question about volcanoes"))
    sources = json.loads(events["sources"])
    assert sources["chunks"] == [] and sources["dropped"] > 0
    assert "close enough" in json.loads(events["token"])["text"]
    assert json.loads(events["done"])["finish_reason"] == "no_relevant_context"


def test_chat_unknown_collection_404(client):
    response = client.post("/chat", json={"collection_id": "missing-123", "question": "hi"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "collection_not_found"
