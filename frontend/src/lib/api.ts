// REST client for the backend API.

import type {
  CollectionDetail,
  CollectionSummary,
  JobSnapshot,
  JobStarted,
  LlmHealth,
  MapQueryPoint,
  RagSettings,
  SettingsResponse,
  VectorMapData,
} from "./types";

export const API_URL: string = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body?.error) return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, "http_error", `Request failed (HTTP ${response.status})`);
}

export function networkError(): ApiError {
  return new ApiError(0, "network", `Cannot reach the backend at ${API_URL}. Is it running?`);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw networkError();
  }
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

function json(body: unknown, token?: string, method = "POST"): RequestInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return { method, headers, body: JSON.stringify(body) };
}

function sourcesForm(files: File[], urls: string[], name?: string): FormData {
  const form = new FormData();
  if (name !== undefined) form.append("name", name);
  files.forEach((file) => form.append("files", file, file.name));
  urls.forEach((url) => form.append("urls", url));
  return form;
}

export const api = {
  llmHealth: (refresh = false) => request<LlmHealth>(`/health/llm${refresh ? "?refresh=true" : ""}`),
  login: (password: string) => request<{ token: string; expires_in: number }>("/auth/login", json({ password })),
  getSettings: () => request<SettingsResponse>("/settings"),
  putSettings: (settings: RagSettings, token: string) => request<SettingsResponse>("/settings", json(settings, token, "PUT")),
  listCollections: () => request<CollectionSummary[]>("/collections"),
  getCollection: (id: string) => request<CollectionDetail>(`/collections/${encodeURIComponent(id)}`),
  createCollection: (name: string, files: File[], urls: string[]) =>
    request<JobStarted>("/collections", { method: "POST", body: sourcesForm(files, urls, name) }),
  addSources: (id: string, files: File[], urls: string[]) =>
    request<JobStarted>(`/collections/${encodeURIComponent(id)}/sources`, { method: "POST", body: sourcesForm(files, urls) }),
  reindex: (id: string) => request<JobStarted>(`/collections/${encodeURIComponent(id)}/reindex`, { method: "POST" }),
  deleteCollection: (id: string) => request<{ deleted: string }>(`/collections/${encodeURIComponent(id)}`, { method: "DELETE" }),
  getMap: (id: string) => request<VectorMapData>(`/collections/${encodeURIComponent(id)}/map`),
  projectQuery: (id: string, q: string) =>
    request<MapQueryPoint>(`/collections/${encodeURIComponent(id)}/map/query?q=${encodeURIComponent(q)}`),
  getJob: (id: string) => request<JobSnapshot>(`/ingest/jobs/${encodeURIComponent(id)}`),
};
