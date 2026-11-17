"""AppContext: the long-lived objects every request shares (stores, open indexes, loaded models)."""

import logging
import threading
import time
from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel

from .auth import LoginRateLimiter
from .config import AppConfig
from .jobs.manager import JobManager
from .llm import create_chat_model
from .rag.embedding import get_embedding_model
from .rag.retrieval import Reranker
from .rag.vectorstore import VectorIndex
from .schemas import LlmHealth, RagSettings, RerankerStatus
from .storage import CollectionStore, SettingsStore

log = logging.getLogger(__name__)

LLM_HEALTH_TTL_S = 60


class AppContext:
    """Everything the API needs, created once per app. Tests swap in fakes via the factories."""

    def __init__(
        self,
        config: AppConfig,
        *,
        embeddings_factory: Callable[[str], Embeddings] = get_embedding_model,
        llm_factory: Callable[..., BaseChatModel] | None = None,
        reranker_factory: Callable[[str], Reranker] = Reranker,
    ):
        self.config = config
        self.settings_store = SettingsStore(config.data_dir / "settings.json")
        self.collections = CollectionStore(config.data_dir / "collections")
        self.jobs = JobManager()
        self.login_limiter = LoginRateLimiter(config.login_max_attempts, config.login_window_s)
        self._embeddings_factory = embeddings_factory
        self._llm_factory = llm_factory or (lambda **kw: create_chat_model(config, **kw))
        self._reranker_factory = reranker_factory
        self._indexes: dict[tuple[str, int], VectorIndex] = {}
        self._indexes_lock = threading.Lock()
        self._reranker: Reranker | None = None
        self._reranker_state = "not_loaded"
        self._reranker_error: str | None = None
        self._reranker_lock = threading.Lock()
        self.llm_health: tuple[float, LlmHealth] | None = None

    # Settings
    def settings(self) -> RagSettings:
        return self.settings_store.load()

    # Models
    def embeddings(self) -> Embeddings:
        return self._embeddings_factory(self.config.embedding_model_name)

    def llm(self, **kwargs) -> BaseChatModel:
        return self._llm_factory(**kwargs)

    # Vector indexes (kept open; Chroma loads persisted data from disk, no re-embedding)
    def index(self, collection_id: str, version: int) -> VectorIndex:
        key = (collection_id, version)
        with self._indexes_lock:
            if key not in self._indexes:
                self._indexes[key] = VectorIndex(self.collections.chroma_dir(collection_id), version, self.embeddings())
            return self._indexes[key]

    def close_indexes(self, collection_id: str, keep_version: int | None = None) -> None:
        with self._indexes_lock:
            for key in [k for k in self._indexes if k[0] == collection_id and k[1] != keep_version]:
                self._indexes.pop(key).close()

    def close_all(self) -> None:
        with self._indexes_lock:
            for index in self._indexes.values():
                index.close()
            self._indexes.clear()

    def warm_up(self) -> None:
        """Load the embedding model and re-open every saved index, so the first question is fast."""
        started = time.perf_counter()
        try:
            self.embeddings()
            for manifest in self.collections.list():
                if manifest.index_version and manifest.embedding_model == self.config.embedding_model_name:
                    count = self.index(manifest.id, manifest.index_version).count()
                    log.info("Loaded index '%s' from disk: %d chunks (no re-embedding)", manifest.name, count)
            log.info("Warm-up finished in %.1fs", time.perf_counter() - started)
            if self.settings().reranker:
                self.load_reranker()
        except Exception as exc:
            log.warning("Warm-up failed: %s", exc.__class__.__name__)

    # Reranker (downloaded on first enable)
    def reranker_status(self) -> RerankerStatus:
        return RerankerStatus(state=self._reranker_state, model=self.config.reranker_model_name, error=self._reranker_error)

    def load_reranker(self) -> Reranker | None:
        with self._reranker_lock:
            if self._reranker is None:
                self._reranker_state, self._reranker_error = "loading", None
                try:
                    self._reranker = self._reranker_factory(self.config.reranker_model_name)
                    self._reranker_state = "ready"
                except Exception as exc:
                    self._reranker_state = "error"
                    self._reranker_error = f"Could not load reranker model ({exc.__class__.__name__}). Check your internet connection for the first download."
                    log.warning("Reranker load failed: %s", exc)
            return self._reranker

    def load_reranker_in_background(self) -> None:
        if self._reranker_state in ("not_loaded", "error"):
            self._reranker_state = "loading"
            threading.Thread(target=self.load_reranker, name="reranker-load", daemon=True).start()
