"""Shared fixtures. The tests run offline: a fake LLM, hashing embeddings and a fake reranker."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.auth import hash_password
from app.config import AppConfig
from app.main import create_app
from app.state import AppContext

from .helpers import FakeReranker, HashingEmbeddings, make_pdf, wait_for_job

ADMIN_PASSWORD = "correct-horse-battery"
FAKE_ANSWER = "Blob storage keeps unstructured data [1]."


@pytest.fixture
def config(tmp_path) -> AppConfig:
    return AppConfig(
        _env_file=None,
        data_dir=tmp_path / "data",
        llm_api_key="sk-test-not-a-real-key-123456",
        llm_base_url="https://llm.invalid/v1",
        admin_password_hash=hash_password(ADMIN_PASSWORD),
        jwt_secret="test-jwt-secret-" + "x" * 40,
        max_upload_mb=1,
    )


@pytest.fixture
def embeddings() -> HashingEmbeddings:
    return HashingEmbeddings()


@pytest.fixture
def llm_responses() -> list[str]:
    return [FAKE_ANSWER]


@pytest.fixture
def make_ctx(config, embeddings, llm_responses):
    def factory(cfg: AppConfig | None = None) -> AppContext:
        return AppContext(
            cfg or config,
            embeddings_factory=lambda _name: embeddings,
            llm_factory=lambda **_kw: FakeListChatModel(responses=list(llm_responses)),
            reranker_factory=FakeReranker,
        )

    return factory


@pytest.fixture
def client(config, make_ctx):
    app = create_app(config, context=make_ctx(), warm_up=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_token(client) -> str:
    response = client.post("/auth/login", json={"password": ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["token"]


SAMPLE_PAGES = [
    [
        "Azure Storage overview.",
        "Blob storage keeps unstructured data such as images and backups.",
        "Access tiers are hot, cool, cold and archive.",
        "Redundancy options include locally redundant and geo-redundant replication.",
        "Lifecycle rules can move old blobs to cheaper tiers automatically.",
    ],
    [
        "Virtual networks.",
        "A virtual network isolates resources and uses subnets with address ranges.",
        "Network security groups filter inbound and outbound traffic.",
        "Peering connects two virtual networks so resources can talk privately.",
        "Route tables override the default system routes for a subnet.",
    ],
]


@pytest.fixture
def indexed_collection(client) -> dict:
    """A collection built from a 2-page PDF plus a Markdown file."""
    files = [
        ("files", ("azure-notes.pdf", make_pdf(SAMPLE_PAGES), "application/pdf")),
        ("files", ("extra.md", b"# Pricing\n\nArchive tier is the cheapest storage tier.\n", "text/markdown")),
    ]
    response = client.post("/collections", data={"name": "Azure notes"}, files=files)
    assert response.status_code == 202, response.text
    body = response.json()
    snapshot = wait_for_job(client, body["job"]["job_id"])
    assert snapshot["stage"] == "done", snapshot
    return client.get(f"/collections/{body['collection']['id']}").json()
