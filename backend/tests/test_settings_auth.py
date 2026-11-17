import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.auth import verify_password
from app.config import AppConfig
from app.main import create_app
from app.schemas import RagSettings

from .conftest import ADMIN_PASSWORD

VALID = {"chunk_size": 800, "chunk_overlap": 100, "retrieval_k": 4, "query_rewrite": False,
         "hybrid_search": True, "reranker": False, "heading_aware_chunking": True}


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_size": 199}, {"chunk_size": 4001}, {"chunk_overlap": -1},
        {"chunk_size": 500, "chunk_overlap": 500}, {"retrieval_k": 0}, {"retrieval_k": 21},
        {"unknown_field": 1},
    ],
)
def test_settings_bounds_rejected(overrides):
    with pytest.raises(ValidationError):
        RagSettings(**{**VALID, **overrides})


def test_settings_bounds_accepted():
    assert RagSettings(**{**VALID, "chunk_size": 200, "chunk_overlap": 199, "retrieval_k": 20}).retrieval_k == 20
    assert RagSettings(**{**VALID, "chunk_size": 4000, "chunk_overlap": 0, "retrieval_k": 1}).chunk_size == 4000


def test_get_settings_is_public(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert response.json()["settings"]["chunk_size"] == 1500


def test_put_settings_without_token_rejected(client, config):
    response = client.put("/settings", json=VALID)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert not (config.data_dir / "settings.json").exists()


def test_put_settings_with_bad_token_rejected(client):
    response = client.put("/settings", json=VALID, headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


def test_put_settings_with_expired_token_rejected(client, config):
    expired = jwt.encode(
        {"sub": "admin", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        config.jwt_secret.get_secret_value(), algorithm="HS256",
    )
    response = client.put("/settings", json=VALID, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_wrong_password_rejected(client):
    response = client.post("/auth/login", json={"password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_password"
    assert "token" not in response.json()


def test_put_settings_with_token_persists(client, admin_token, config):
    response = client.put("/settings", json=VALID, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 200, response.text
    saved = json.loads((config.data_dir / "settings.json").read_text())
    assert saved["chunk_size"] == 800 and saved["hybrid_search"] is True
    assert client.get("/settings").json()["settings"]["retrieval_k"] == 4


def test_put_invalid_settings_with_token_returns_readable_422(client, admin_token):
    response = client.put("/settings", json={**VALID, "chunk_overlap": 900}, headers={"Authorization": f"Bearer {admin_token}"})
    assert response.status_code == 422
    assert "chunk_overlap must be smaller than chunk_size" in response.json()["error"]["message"]


def test_login_rate_limited_after_five_attempts(client):
    codes = [client.post("/auth/login", json={"password": f"guess-{i}"}).status_code for i in range(5)]
    assert codes == [401] * 5
    blocked = client.post("/auth/login", json={"password": ADMIN_PASSWORD})
    assert blocked.status_code == 429
    assert "Too many login attempts" in blocked.json()["error"]["message"]
    assert int(blocked.headers["Retry-After"]) > 0


def test_login_without_configured_password(tmp_path, make_ctx):
    config = AppConfig(_env_file=None, data_dir=tmp_path / "d", admin_password_hash=None, jwt_secret=None)
    from fastapi.testclient import TestClient

    with TestClient(create_app(config, context=make_ctx(config), warm_up=False)) as c:
        response = c.post("/auth/login", json={"password": "anything"})
    assert response.status_code == 503
    assert "set_admin_password" in response.json()["error"]["message"]


def test_verify_password():
    from app.auth import hash_password

    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("s3cret-pasS", stored)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_login_response_never_contains_hash(client, config):
    response = client.post("/auth/login", json={"password": ADMIN_PASSWORD})
    assert config.admin_password_hash.get_secret_value() not in response.text
    assert config.jwt_secret.get_secret_value() not in response.text
