import asyncio

import httpx
import openai

from app.config import AppConfig
from app.errors import redact
from app.llm import check_llm, describe_llm_error

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


def _status_error(cls, status: int, message: str):
    response = httpx.Response(status, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    return cls(message, response=response, body={"error": {"message": message}})


def test_openrouter_key_is_fallback_for_llm_api_key(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\n")
    cfg = AppConfig(_env_file=env)
    assert cfg.llm_key_value() == KEY
    assert cfg.llm_base_url == "https://openrouter.ai/api/v1"
    assert cfg.llm_model == "deepseek/deepseek-v4.1-flash"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\nLLM_API_KEY=preferred-key-123\n")
    assert AppConfig(_env_file=env).llm_key_value() == "preferred-key-123"
    assert KEY not in repr(AppConfig(_env_file=env))


def test_ollama_needs_no_real_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LLM_BASE_URL=http://localhost:11434/v1\nLLM_MODEL=llama3.2\n")
    assert AppConfig(_env_file=env).llm_key_value()


def test_error_messages_are_actionable_and_secret_free():
    cfg = AppConfig(_env_file=None, llm_api_key=KEY)
    message, hint = describe_llm_error(_status_error(openai.AuthenticationError, 401, f"Bad key {KEY}"), cfg)
    assert "rejected the API key" in message and ".env" in hint
    assert KEY not in redact(message, cfg.secret_values())
    message, hint = describe_llm_error(_status_error(openai.NotFoundError, 404, "No endpoints found"), cfg)
    assert "not found" in message and "LLM_MODEL" in hint
    message, hint = describe_llm_error(_status_error(openai.BadRequestError, 400, "x is not a valid model ID"), cfg)
    assert "LLM_MODEL" in hint


def test_redact_removes_secrets_and_key_shapes():
    text = f"failed with {KEY} and Bearer abcdefghijklmnop and custom-secret-value"
    cleaned = redact(text, ["custom-secret-value"])
    assert KEY not in cleaned and "abcdefghijklmnop" not in cleaned and "custom-secret-value" not in cleaned


def test_health_reports_missing_key():
    cfg = AppConfig(_env_file=None, llm_api_key=None)
    result = asyncio.run(check_llm(cfg))
    assert result.ok is False
    assert "No LLM API key" in result.error and "LLM_API_KEY" in result.hint


def test_health_reports_unknown_model_with_suggestions(monkeypatch):
    cfg = AppConfig(_env_file=None, llm_api_key=KEY, llm_model="openai/gpt-4o-mni")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}, {"id": "openai/gpt-4o"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    result = asyncio.run(check_llm(cfg))
    assert result.ok is False
    assert "openai/gpt-4o-mni" in result.error
    assert "openai/gpt-4o-mini" in result.suggestions
    assert KEY not in result.model_dump_json()
