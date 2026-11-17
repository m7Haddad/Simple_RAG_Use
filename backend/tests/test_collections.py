import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import RagSettings
from app.scripts.set_admin_password import update_env_file
from app.storage import Manifest, requires_reindex, stale_reasons

from .helpers import parse_sse, wait_for_job

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _manifest(**overrides) -> Manifest:
    now = datetime.now(UTC)
    base = dict(id="kb-1", name="KB", created_at=now, updated_at=now, chunk_size=1500, chunk_overlap=200,
                heading_aware_chunking=False, embedding_model=MODEL, index_version=1)
    return Manifest(**{**base, **overrides})


def test_stale_logic():
    settings = RagSettings()
    assert stale_reasons(_manifest(), settings, MODEL) == []
    assert stale_reasons(_manifest(chunk_size=None, embedding_model=None, index_version=0), settings, MODEL) == []
    assert stale_reasons(_manifest(chunk_size=800), settings, MODEL) == ["chunk size 800 → 1500"]
    assert stale_reasons(_manifest(chunk_overlap=0), settings, MODEL) == ["chunk overlap 0 → 200"]
    assert "heading-aware" in stale_reasons(_manifest(heading_aware_chunking=True), settings, MODEL)[0]
    assert "embedding model" in stale_reasons(_manifest(), settings, "other/model")[0]
    # retrieval_k and the query-time flags never make an index stale
    query_only = RagSettings(retrieval_k=12, hybrid_search=True, reranker=True, query_rewrite=False)
    assert stale_reasons(_manifest(), query_only, MODEL) == []
    assert requires_reindex(_manifest(), "other/model") and not requires_reindex(_manifest(), MODEL)


def test_manifest_written(indexed_collection, config):
    manifest = json.loads((config.data_dir / "collections" / indexed_collection["id"] / "manifest.json").read_text(encoding="utf-8"))
    for key in ("name", "sources", "chunk_size", "chunk_overlap", "embedding_model", "created_at", "updated_at", "chunk_count"):
        assert key in manifest
    raw_files = list((config.data_dir / "collections" / indexed_collection["id"] / "raw").glob("*.json"))
    assert len(raw_files) == 2
    raw = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert raw["pages"] and {"number", "label", "text"} <= set(raw["pages"][0])


def test_chunk_setting_change_marks_stale_and_reindex_fixes_it(client, indexed_collection, admin_token, embeddings):
    cid = indexed_collection["id"]
    settings = client.get("/settings").json()["settings"]
    settings.update(chunk_size=200, chunk_overlap=20)
    assert client.put("/settings", json=settings, headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200

    listed = {c["id"]: c for c in client.get("/collections").json()}
    assert listed[cid]["stale"] is True
    assert "chunk size 1500 → 200" in listed[cid]["stale_reasons"]
    assert cid in client.get("/settings").json()["stale_collections"]

    embedded_before = embeddings.documents_embedded
    started = client.post(f"/collections/{cid}/reindex")
    assert started.status_code == 202
    snapshot = wait_for_job(client, started.json()["job"]["job_id"])
    assert snapshot["stage"] == "done", snapshot

    after = client.get(f"/collections/{cid}").json()
    assert after["stale"] is False
    assert after["indexed_with"]["chunk_size"] == 200
    assert after["chunk_count"] > indexed_collection["chunk_count"]
    assert embeddings.documents_embedded - embedded_before == after["chunk_count"]

    # The new index answers questions and its chunks respect the new size.
    events = parse_sse(client.post("/chat", json={"collection_id": cid, "question": "blob storage"}).text)
    chunks = json.loads(dict(events)["sources"])["chunks"]
    assert chunks and all(c["chars"] <= 200 for c in chunks)


def test_restart_reloads_index_without_reembedding(config, make_ctx, embeddings, indexed_collection):
    embedded_at_ingest = embeddings.documents_embedded
    assert embedded_at_ingest == 3

    with TestClient(create_app(config, context=make_ctx(), warm_up=False)) as restarted:
        listed = restarted.get("/collections").json()
        assert listed[0]["chunk_count"] == 3
        events = parse_sse(restarted.post("/chat", json={"collection_id": indexed_collection["id"], "question": "blob storage"}).text)
        assert json.loads(dict(events)["sources"])["chunks"], "persisted index must answer after restart"
    assert embeddings.documents_embedded == embedded_at_ingest, "restart must not re-embed documents"


def test_add_sources_to_existing_collection(client, indexed_collection):
    cid = indexed_collection["id"]
    response = client.post(f"/collections/{cid}/sources", files=[("files", ("more.txt", b"Queues deliver messages between services.", "text/plain"))])
    assert response.status_code == 202
    assert wait_for_job(client, response.json()["job"]["job_id"])["stage"] == "done"
    after = client.get(f"/collections/{cid}").json()
    assert after["source_count"] == 3 and after["chunk_count"] == 4


def test_delete_collection(client, indexed_collection, config):
    cid = indexed_collection["id"]
    # open the index first, so deletion has to release Chroma's files (matters on Windows)
    client.post("/chat", json={"collection_id": cid, "question": "storage"})
    assert client.delete(f"/collections/{cid}").status_code == 200
    assert client.get(f"/collections/{cid}").status_code == 404
    assert all(c["id"] != cid for c in client.get("/collections").json())


def test_env_update_preserves_other_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"# my settings\r\nOPENROUTER_API_KEY=sk-or-v1-keepme\r\nJWT_SECRET=old\r\nLLM_MODEL=some/model")
    update_env_file(env, {"ADMIN_PASSWORD_HASH": "$argon2id$v=19$abc", "JWT_SECRET": "new"})
    text = env.read_bytes().decode()
    assert text.startswith("# my settings\r\nOPENROUTER_API_KEY=sk-or-v1-keepme\r\nJWT_SECRET='new'\r\nLLM_MODEL=some/model\r\n")
    assert text.endswith("ADMIN_PASSWORD_HASH='$argon2id$v=19$abc'\r\n")
    assert text.count("JWT_SECRET") == 1


def test_env_update_reads_back_with_settings(tmp_path):
    from app.config import AppConfig

    env = tmp_path / ".env"
    env.write_text("OPENROUTER_API_KEY=sk-or-v1-abc123")  # no trailing newline, like the real file
    update_env_file(env, {"ADMIN_PASSWORD_HASH": "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA", "JWT_SECRET": "s3cr3t"})
    cfg = AppConfig(_env_file=env)
    assert cfg.admin_password_hash.get_secret_value() == "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"
    assert cfg.llm_key_value() == "sk-or-v1-abc123"
