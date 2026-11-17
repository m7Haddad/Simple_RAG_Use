import { API_URL, networkError, toApiError } from "./api";

export type SseHandler = (event: string, data: unknown) => void;

/**
 * Reads a Server-Sent Events stream with fetch (EventSource cannot POST).
 * Resolves when the server closes the stream; rejects with ApiError on HTTP errors.
 */
export async function streamSse(path: string, init: RequestInit, onEvent: SseHandler, signal?: AbortSignal): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, signal, headers: { Accept: "text/event-stream", ...init.headers } });
  } catch {
    if (signal?.aborted) return;
    throw networkError();
  }
  if (!response.ok) throw await toApiError(response);
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        dispatch(block, onEvent);
      }
    }
  } catch (err) {
    if (signal?.aborted) return;
    throw err;
  } finally {
    reader.releaseLock();
  }
}

function dispatch(block: string, onEvent: SseHandler) {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return;
  const raw = data.join("\n");
  try {
    onEvent(event, JSON.parse(raw));
  } catch {
    onEvent(event, raw);
  }
}
