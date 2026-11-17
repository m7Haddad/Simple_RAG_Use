"""The API's request, response and settings models (pydantic)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .rag.chunking import CHUNK_SIZE_MAX, CHUNK_SIZE_MIN


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Settings ----------------------------------------------------------------

INDEX_SETTING_FIELDS = ("chunk_size", "chunk_overlap", "heading_aware_chunking")


class RagSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_size: int = Field(1500, ge=CHUNK_SIZE_MIN, le=CHUNK_SIZE_MAX)
    chunk_overlap: int = Field(200, ge=0)
    retrieval_k: int = Field(6, ge=1, le=20)
    # Relevance cutoff: chunks with relevance (1 - cosine distance) below this are dropped. 0 = off.
    min_relevance: float = Field(0.0, ge=0.0, le=0.95)
    query_rewrite: bool = True
    hybrid_search: bool = False
    reranker: bool = False
    heading_aware_chunking: bool = False

    @model_validator(mode="after")
    def _overlap_below_size(self) -> "RagSettings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class RerankerStatus(BaseModel):
    state: Literal["not_loaded", "loading", "ready", "error"]
    model: str
    error: str | None = None


class SettingsResponse(BaseModel):
    settings: RagSettings
    index_fields: list[str] = list(INDEX_SETTING_FIELDS)
    embedding_model: str
    reranker: RerankerStatus
    stale_collections: list[str] = []


# --- Auth --------------------------------------------------------------------


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


# --- Health ------------------------------------------------------------------


class LlmHealth(BaseModel):
    ok: bool
    base_url: str
    model: str
    provider: str
    latency_ms: float | None = None
    error: str | None = None
    hint: str | None = None
    suggestions: list[str] = []
    checked_at: datetime


# --- Collections ---------------------------------------------------------------


class IndexSettings(BaseModel):
    chunk_size: int
    chunk_overlap: int
    heading_aware_chunking: bool
    embedding_model: str


class SourceInfo(BaseModel):
    source_id: str
    name: str
    kind: Literal["file", "url"]
    original: str
    content_type: str | None = None
    pages: int = 0
    characters: int = 0
    chunks: int = 0
    added_at: datetime


class CollectionSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    chunk_count: int
    source_count: int
    indexed_with: IndexSettings | None
    stale: bool
    stale_reasons: list[str]
    reindex_required: bool
    active_job_id: str | None = None


class CollectionDetail(CollectionSummary):
    sources: list[SourceInfo]


class JobInfo(BaseModel):
    job_id: str
    kind: Literal["ingest", "reindex"]
    collection_id: str
    stage: str


class JobStarted(BaseModel):
    collection: CollectionSummary
    job: JobInfo


class DeleteResponse(BaseModel):
    deleted: str


# --- Vector map ------------------------------------------------------------------


class MapPoint(BaseModel):
    chunk_id: int
    source_id: str | None = None
    source_name: str | None = None
    location: str | None = None
    heading: str | None = None
    snippet: str
    x: float
    y: float


class VectorMapResponse(BaseModel):
    index_version: int
    dimensions: int
    explained_variance: list[float]  # share of the total spread kept by each of the 2 axes
    points: list[MapPoint]


class MapQueryResponse(BaseModel):
    query: str
    x: float
    y: float


# --- Chat ----------------------------------------------------------------------


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
