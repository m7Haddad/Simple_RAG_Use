"""The FastAPI application factory: wires the config, shared state, CORS, error handlers and routers together."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, chat, collections, health, ingest, settings
from .config import AppConfig, get_config
from .errors import install_error_handlers, install_log_redaction
from .llm import provider_name
from .state import AppContext

log = logging.getLogger("app")


def create_app(config: AppConfig | None = None, *, context: AppContext | None = None, warm_up: bool = True) -> FastAPI:
    """Build the FastAPI app. Tests pass their own config and context to swap in fakes."""
    config = config or get_config()
    ctx = context or AppContext(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        install_log_redaction(config.secret_values())
        ctx.collections.purge_deleted()
        log.info(
            "LLM: %s model=%s base_url=%s key=%s",
            provider_name(config.llm_base_url), config.llm_model, config.llm_base_url,
            "configured" if config.llm_key_value() else "MISSING",
        )
        log.info("Data directory: %s", config.data_dir)
        if not config.admin_password_hash:
            log.warning("No admin password set: run 'python -m app.scripts.set_admin_password' to enable settings changes")
        if warm_up:
            threading.Thread(target=ctx.warm_up, name="warm-up", daemon=True).start()
        yield
        ctx.jobs.shutdown()
        ctx.close_all()

    app = FastAPI(title="Local RAG Studio API", version="1.0.0", lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
    )
    install_error_handlers(app)
    for module in (health, auth, settings, collections, ingest, chat):
        app.include_router(module.router)
    return app
