// Data hooks: theme, LLM health, collections, settings and live job progress.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { streamSse } from "../lib/sse";
import type { CollectionSummary, JobSnapshot, LlmHealth, SettingsResponse } from "../lib/types";

export function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem("theme", dark ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

export function useLlmHealth() {
  const [health, setHealth] = useState<LlmHealth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const check = useCallback(async (refresh = false) => {
    setChecking(true);
    try {
      setHealth(await api.llmHealth(refresh));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Health check failed");
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(() => check(), 5 * 60_000);
    return () => clearInterval(timer);
  }, [check]);

  return { health, error, checking, recheck: () => check(true) };
}

export function useCollections() {
  const [collections, setCollections] = useState<CollectionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setCollections(await api.listCollections());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load collections");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const upsert = useCallback((summary: CollectionSummary) => {
    setCollections((list) => [summary, ...(list ?? []).filter((c) => c.id !== summary.id)]);
  }, []);

  return { collections, error, refresh, upsert };
}

export function useSettings() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.getSettings());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load settings");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, setData, error, refresh };
}

/** Follows an ingest/re-index job over SSE. Calls onFinish once when it reaches done/error. */
export function useJobStream(jobId: string | null, onFinish?: (snapshot: JobSnapshot) => void) {
  const [snapshot, setSnapshot] = useState<JobSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  useEffect(() => {
    if (!jobId) {
      setSnapshot(null);
      return;
    }
    const controller = new AbortController();
    let finished = false;
    setSnapshot(null);
    setError(null);

    const handle = (_event: string, data: unknown) => {
      const snap = data as JobSnapshot;
      setSnapshot(snap);
      if (!finished && (snap.stage === "done" || snap.stage === "error")) {
        finished = true;
        finishRef.current?.(snap);
      }
    };

    const follow = async () => {
      for (let attempt = 0; attempt < 5 && !controller.signal.aborted && !finished; attempt++) {
        try {
          await streamSse(`/ingest/jobs/${encodeURIComponent(jobId)}/events`, {}, handle, controller.signal);
          if (finished) return;
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            setError(err.message);
            return;
          }
        }
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
      if (!finished && !controller.signal.aborted) setError("Lost connection to the progress stream.");
    };
    follow();
    return () => controller.abort();
  }, [jobId]);

  return { snapshot, error };
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    onChange();
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
