// TypeScript mirrors of the backend's API models (see backend/app/schemas.py).

export interface RagSettings {
  chunk_size: number;
  chunk_overlap: number;
  retrieval_k: number;
  min_relevance: number;
  query_rewrite: boolean;
  hybrid_search: boolean;
  reranker: boolean;
  heading_aware_chunking: boolean;
}

export interface RerankerStatus {
  state: "not_loaded" | "loading" | "ready" | "error";
  model: string;
  error: string | null;
}

export interface SettingsResponse {
  settings: RagSettings;
  index_fields: (keyof RagSettings)[];
  embedding_model: string;
  reranker: RerankerStatus;
  stale_collections: string[];
}

export interface LlmHealth {
  ok: boolean;
  base_url: string;
  model: string;
  provider: string;
  latency_ms: number | null;
  error: string | null;
  hint: string | null;
  suggestions: string[];
  checked_at: string;
}

export interface IndexSettings {
  chunk_size: number;
  chunk_overlap: number;
  heading_aware_chunking: boolean;
  embedding_model: string;
}

export interface SourceInfo {
  source_id: string;
  name: string;
  kind: "file" | "url";
  original: string;
  content_type: string | null;
  pages: number;
  characters: number;
  chunks: number;
  added_at: string;
}

export interface CollectionSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  chunk_count: number;
  source_count: number;
  indexed_with: IndexSettings | null;
  stale: boolean;
  stale_reasons: string[];
  reindex_required: boolean;
  active_job_id: string | null;
}

export interface CollectionDetail extends CollectionSummary {
  sources: SourceInfo[];
}

export interface JobInfo {
  job_id: string;
  kind: "ingest" | "reindex";
  collection_id: string;
  stage: string;
}

export interface JobStarted {
  collection: CollectionSummary;
  job: JobInfo;
}

export type JobStage = "queued" | "loading" | "splitting" | "embedding" | "indexing" | "done" | "error";

export interface JobSource {
  source_id: string;
  name: string;
  kind: "file" | "url";
  status: "pending" | "loading" | "loaded" | "indexed" | "error";
  pages: number;
  characters: number;
  chunks: number;
  error: string | null;
}

export interface SampleChunk {
  chunk_id: number;
  source_name: string;
  location: string;
  heading?: string | null;
  chars: number;
  text: string;
}

export interface JobSnapshot {
  seq: number;
  job_id: string;
  kind: "ingest" | "reindex";
  collection_id: string;
  stage: JobStage;
  message: string;
  elapsed_s: number;
  stats: { pages: number; characters: number; chunks: number; embedded: number; embedding_pct: number; indexed: number };
  sources: JobSource[];
  sample_chunks: SampleChunk[];
  error: string | null;
}

export interface RetrievedChunk {
  rank: number;
  chunk_id: number;
  source_id: string;
  source_name: string;
  page: number;
  location: string;
  heading: string | null;
  distance: number | null;
  relevance: number | null;
  vector_rank: number | null;
  bm25_rank: number | null;
  rerank_score: number | null;
  hybrid_score?: number | null; // 0..1, hybrid search only (1 = ranked first by both vector and keyword search)
  rerank_relevance?: number | null; // 0..1, reranker only (the cross-encoder's probability of relevance)
  chars: number;
  snippet: string;
  text: string;
}

export interface SourcesEvent {
  query: string;
  mode: string;
  dropped?: number;
  chunks: RetrievedChunk[];
}

export interface PromptEvent {
  messages: { role: string; content: string }[];
  text: string;
}

export interface RewriteEvent {
  original: string;
  rewritten: string;
  ms: number;
}

export type Timings = Partial<
  Record<"rewrite_ms" | "embed_ms" | "search_ms" | "bm25_ms" | "rerank_ms" | "retrieval_ms" | "ttft_ms" | "generation_ms" | "total_ms", number>
>;

export interface MapPoint {
  chunk_id: number;
  source_id: string | null;
  source_name: string | null;
  location: string | null;
  heading: string | null;
  snippet: string;
  x: number;
  y: number;
}

export interface VectorMapData {
  index_version: number;
  dimensions: number;
  explained_variance: number[];
  points: MapPoint[];
}

export interface MapQueryPoint {
  query: string;
  x: number;
  y: number;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

export interface AssistantMessage {
  id: string;
  role: "assistant";
  question: string;
  content: string;
  status: "streaming" | "done" | "stopped" | "error";
  sources?: SourcesEvent;
  prompt?: PromptEvent;
  rewrite?: RewriteEvent;
  timings?: Timings;
  notices: string[];
  error?: { message: string; hint?: string };
  settings: { k: number; hybrid: boolean; reranker: boolean; rewrite: boolean };
}

export type Message = UserMessage | AssistantMessage;
