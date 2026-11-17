// Chat state: one conversation per collection, and the SSE stream that fills in each answer.

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { uid } from "../lib/format";
import { streamSse } from "../lib/sse";
import type { AssistantMessage, ChatTurn, Message, PromptEvent, RagSettings, RewriteEvent, SourcesEvent, Timings } from "../lib/types";

const MAX_HISTORY = 6;
const STORAGE_KEY = "chats:v1";
const MAX_SAVED_MESSAGES = 100; // per collection; older messages are dropped from storage

type Threads = Record<string, Message[]>;

function loadThreads(): Threads {
  try {
    const threads = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Threads;
    // An answer that was still streaming when the tab closed can never finish.
    for (const id of Object.keys(threads)) {
      threads[id] = threads[id].map((m) => (m.role === "assistant" && m.status === "streaming" ? { ...m, status: "stopped" } : m));
    }
    return threads;
  } catch {
    return {};
  }
}

/** Drop the bulky Inspector data (full prompt, full chunk text) so a slimmed copy fits the storage quota. */
function slim(threads: Threads): Threads {
  return Object.fromEntries(
    Object.entries(threads).map(([id, list]) => [
      id,
      list.map((m) =>
        m.role === "assistant"
          ? { ...m, prompt: undefined, sources: m.sources && { ...m.sources, chunks: m.sources.chunks.map((c) => ({ ...c, text: c.snippet })) } }
          : m,
      ),
    ]),
  );
}

function saveThreads(threads: Threads) {
  const trimmed = Object.fromEntries(Object.entries(threads).map(([id, list]) => [id, list.slice(-MAX_SAVED_MESSAGES)]));
  for (const candidate of [trimmed, slim(trimmed)]) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(candidate));
      return;
    } catch {
      /* quota exceeded or storage unavailable: try the slimmed copy, then give up */
    }
  }
}

/** Conversations per collection, saved in this browser's localStorage so they survive a reload. */
export function useChatStore() {
  const [threads, setThreads] = useState<Threads>(loadThreads);
  const update = useCallback((collectionId: string, fn: (messages: Message[]) => Message[]) => {
    setThreads((all) => ({ ...all, [collectionId]: fn(all[collectionId] ?? []) }));
  }, []);
  /** Forget the chats of collections that no longer exist. */
  const prune = useCallback((keep: string[]) => {
    setThreads((all) => {
      const kept = Object.fromEntries(Object.entries(all).filter(([id]) => keep.includes(id)));
      return Object.keys(kept).length === Object.keys(all).length ? all : kept;
    });
  }, []);

  // Save once an answer has finished, not on every streamed token.
  const streaming = Object.values(threads).some((list) => list.some((m) => m.role === "assistant" && m.status === "streaming"));
  useEffect(() => {
    if (!streaming) saveThreads(threads);
  }, [threads, streaming]);

  return { threads, update, prune };
}

export type ChatStore = ReturnType<typeof useChatStore>;

export function useChat(collectionId: string, store: ChatStore, settings: RagSettings | null) {
  const messages = store.threads[collectionId] ?? [];
  const controller = useRef<AbortController | null>(null);
  const streaming = messages.some((m) => m.role === "assistant" && m.status === "streaming");

  const patch = useCallback(
    (id: string, fn: (m: AssistantMessage) => AssistantMessage) =>
      store.update(collectionId, (list) => list.map((m) => (m.id === id && m.role === "assistant" ? fn(m) : m))),
    [collectionId, store],
  );

  const send = useCallback(
    async (question: string) => {
      const history: ChatTurn[] = messages
        .filter((m) => m.role === "user" || (m.status !== "error" && m.content))
        .slice(-MAX_HISTORY)
        .map((m) => ({ role: m.role, content: m.content }));
      const assistantId = uid();
      store.update(collectionId, (list) => [
        ...list,
        { id: uid(), role: "user", content: question },
        {
          id: assistantId,
          role: "assistant",
          question,
          content: "",
          status: "streaming",
          notices: [],
          settings: {
            k: settings?.retrieval_k ?? 0,
            hybrid: !!settings?.hybrid_search,
            reranker: !!settings?.reranker,
            rewrite: !!settings?.query_rewrite,
          },
        },
      ]);

      const abort = new AbortController();
      controller.current = abort;
      try {
        await streamSse(
          "/chat",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ collection_id: collectionId, question, history }),
          },
          (event, data) => {
            switch (event) {
              case "rewrite":
                patch(assistantId, (m) => ({ ...m, rewrite: data as RewriteEvent }));
                break;
              case "sources":
                patch(assistantId, (m) => ({ ...m, sources: data as SourcesEvent }));
                break;
              case "prompt":
                patch(assistantId, (m) => ({ ...m, prompt: data as PromptEvent }));
                break;
              case "token":
                patch(assistantId, (m) => ({ ...m, content: m.content + (data as { text: string }).text }));
                break;
              case "timings":
                patch(assistantId, (m) => ({ ...m, timings: data as Timings }));
                break;
              case "notice":
                patch(assistantId, (m) => ({ ...m, notices: [...m.notices, (data as { message: string }).message] }));
                break;
              case "done":
                patch(assistantId, (m) => ({ ...m, status: "done" }));
                break;
              case "error": {
                const e = data as { message: string; hint?: string };
                patch(assistantId, (m) => ({ ...m, status: "error", error: { message: e.message, hint: e.hint } }));
                break;
              }
            }
          },
          abort.signal,
        );
        patch(assistantId, (m) => (m.status === "streaming" ? { ...m, status: abort.signal.aborted ? "stopped" : "done" } : m));
      } catch (err) {
        const message = err instanceof ApiError ? err.message : "The answer stream failed";
        patch(assistantId, (m) => ({ ...m, status: "error", error: { message } }));
      } finally {
        if (controller.current === abort) controller.current = null;
      }
    },
    [collectionId, messages, patch, settings, store],
  );

  const stop = useCallback(() => controller.current?.abort(), []);
  const clear = useCallback(() => store.update(collectionId, () => []), [collectionId, store]);

  return { messages, streaming, send, stop, clear };
}
