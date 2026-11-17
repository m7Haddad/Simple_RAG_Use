"""
The chat-model client: creating it, checking that it works, and turning provider
errors into messages a person can act on.
"""

import asyncio
import difflib
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import openai
from langchain_openai import ChatOpenAI

from .config import AppConfig
from .errors import redact
from .schemas import LlmHealth

KEY_HINT = "Add LLM_API_KEY=... (OPENROUTER_API_KEY also works) to the .env file in the project root, then restart the backend."


class LlmConfigError(Exception):
    """The LLM cannot be used as configured (for example, no API key is set)."""


def provider_name(base_url: str) -> str:
    host = urlparse(base_url).hostname or base_url
    if "openrouter.ai" in host:
        return "OpenRouter"
    if urlparse(base_url).port == 11434:
        return "Ollama"
    if "openai.com" in host:
        return "OpenAI"
    return host


def create_chat_model(config: AppConfig, *, max_tokens: int | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """Create the chat client for the configured OpenAI-compatible endpoint."""
    key = config.llm_key_value()
    if not key:
        raise LlmConfigError(f"No LLM API key configured. {KEY_HINT}")
    headers = {"HTTP-Referer": "http://localhost", "X-Title": "Local RAG Studio"} if "openrouter.ai" in config.llm_base_url else None
    return ChatOpenAI(
        model=config.llm_model,
        api_key=key,
        base_url=config.llm_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=config.llm_timeout_s,
        max_retries=1,
        default_headers=headers,
    )


def model_hint(config: AppConfig) -> str:
    if provider_name(config.llm_base_url) == "OpenRouter":
        return "Fix LLM_MODEL in .env and restart the backend. Browse valid names at https://openrouter.ai/models."
    return f"Fix LLM_MODEL in .env (for Ollama, run: ollama pull {config.llm_model}) and restart the backend."


def describe_llm_error(exc: Exception, config: AppConfig) -> tuple[str, str]:
    """Turn a provider exception into (message, hint) a person can act on. Never includes the key."""
    model, base = config.llm_model, config.llm_base_url
    provider = provider_name(base)
    detail = _provider_detail(exc)
    if isinstance(exc, LlmConfigError):
        return str(exc), KEY_HINT
    if isinstance(exc, openai.AuthenticationError):
        return f"{provider} rejected the API key (HTTP 401){detail}", KEY_HINT
    if isinstance(exc, openai.NotFoundError):
        return f"Model '{model}' was not found at {provider}{detail}", model_hint(config)
    if isinstance(exc, openai.PermissionDeniedError):
        return f"{provider} denied access to '{model}' (HTTP 403){detail}", "Check that your key is allowed to use this model."
    if isinstance(exc, openai.RateLimitError):
        return f"{provider} is rate-limiting requests (HTTP 429){detail}", "Wait a minute and check again, or pick a less busy model."
    if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
        return f"{provider} says the account has insufficient credits (HTTP 402){detail}", "Add credits or switch to a free model."
    if isinstance(exc, openai.BadRequestError):
        return f"{provider} rejected the request for model '{model}'{detail}", model_hint(config)
    if isinstance(exc, openai.APIStatusError):
        return f"{provider} returned HTTP {exc.status_code}{detail}", "Try again; if it persists, check the provider's status page."
    if isinstance(exc, (openai.APITimeoutError, asyncio.TimeoutError, TimeoutError)):
        return f"Timed out waiting for {provider}", "The provider may be slow or overloaded. Try again."
    if isinstance(exc, (openai.APIConnectionError, httpx.ConnectError)):
        hint = "Is Ollama running? Start it with: ollama serve" if provider == "Ollama" else "Check LLM_BASE_URL in .env and your network connection."
        return f"Cannot reach {base}", hint
    return f"LLM call failed: {exc.__class__.__name__}{detail}", "Check the backend log for details."


def _provider_detail(exc: Exception) -> str:
    message = ""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        message = err.get("message", "") if isinstance(err, dict) else str(err)
    message = message or getattr(exc, "message", "") or ""
    message = " ".join(str(message).split())[:240]
    return f": {message}" if message else ""


async def check_llm(config: AppConfig) -> LlmHealth:
    """Check the model exists (provider model list) and answers (a tiny completion)."""
    base, model = config.llm_base_url, config.llm_model
    provider = provider_name(base)
    secrets = config.secret_values()

    def result(ok: bool, error: str | None = None, hint: str | None = None, latency: float | None = None, suggestions=()):
        return LlmHealth(
            ok=ok, base_url=base, model=model, provider=provider,
            latency_ms=latency, error=redact(error, secrets) if error else None, hint=hint,
            suggestions=list(suggestions), checked_at=datetime.now(UTC),
        )

    key = config.llm_key_value()
    if not key:
        return result(False, "No LLM API key configured", KEY_HINT)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
        if resp.status_code == 200:
            ids = [m.get("id") for m in resp.json().get("data", []) if isinstance(m, dict)]
            if ids and model not in ids:
                suggestions = difflib.get_close_matches(model, ids, n=5, cutoff=0.5)
                return result(False, f"Model '{model}' is not in {provider}'s model list", model_hint(config), suggestions=suggestions)
    except httpx.ConnectError as exc:
        message, hint = describe_llm_error(exc, config)
        return result(False, message, hint)
    except (httpx.HTTPError, ValueError):
        pass  # some servers have no model list; the test call below still decides

    started = time.perf_counter()
    try:
        llm = create_chat_model(config, max_tokens=5)
        await asyncio.wait_for(llm.ainvoke("Reply with the single word OK."), timeout=45)
    except Exception as exc:  # every failure becomes an actionable message
        message, hint = describe_llm_error(exc, config)
        return result(False, message, hint)
    return result(True, latency=round((time.perf_counter() - started) * 1000, 1))
