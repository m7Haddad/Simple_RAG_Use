// Settings drawer: the chunking and retrieval settings, and re-indexing of stale collections.

import { CheckCircle2, Lock, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useJobStream } from "../hooks";
import { api, ApiError } from "../lib/api";
import type { CollectionSummary, RagSettings, SettingsResponse } from "../lib/types";
import { useAdmin } from "../state/auth";
import { Badge, Button, cx, Drawer, ErrorNote, Meter, Skeleton, Toggle } from "./ui";

const DEFAULTS: RagSettings = {
  chunk_size: 1500,
  chunk_overlap: 200,
  retrieval_k: 6,
  min_relevance: 0,
  query_rewrite: true,
  hybrid_search: false,
  reranker: false,
  heading_aware_chunking: false,
};

export function SettingsDrawer({
  open,
  onClose,
  data,
  onSaved,
  collections,
  jobs,
  onReindex,
  refresh,
}: {
  open: boolean;
  onClose: () => void;
  data: SettingsResponse | null;
  onSaved: (resp: SettingsResponse) => void;
  collections: CollectionSummary[];
  jobs: Record<string, string>;
  onReindex: (collectionId: string) => Promise<void>;
  refresh: () => void;
}) {
  const admin = useAdmin();
  const [draft, setDraft] = useState<RagSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [reindexed, setReindexed] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (open && data) {
      setDraft(data.settings);
      setError(null);
      setSaved(false);
    }
  }, [open]);

  // While the reranker model downloads, poll so its status updates.
  useEffect(() => {
    if (!open || data?.reranker.state !== "loading") return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [open, data?.reranker.state, refresh]);

  const current = data?.settings;
  const dirty = !!draft && !!current && (Object.keys(draft) as (keyof RagSettings)[]).some((k) => draft[k] !== current[k]);
  const indexDirty = !!draft && !!current && (draft.chunk_size !== current.chunk_size || draft.chunk_overlap !== current.chunk_overlap || draft.heading_aware_chunking !== current.heading_aware_chunking);
  const overlapInvalid = !!draft && draft.chunk_overlap >= draft.chunk_size;

  const set = <K extends keyof RagSettings>(key: K, value: RagSettings[K]) => {
    setSaved(false);
    setDraft((d) => {
      if (!d) return d;
      const next = { ...d, [key]: value };
      if (key === "chunk_size" && next.chunk_overlap >= next.chunk_size) next.chunk_overlap = Math.max(0, next.chunk_size - 50);
      return next;
    });
  };

  const save = async () => {
    if (!draft || overlapInvalid) return;
    setSaving(true);
    setError(null);
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
        const token = await admin.ensureToken();
        if (!token) {
          setError("Not saved: the admin password is required to change settings.");
          return;
        }
        try {
          const resp = await api.putSettings(draft, token);
          onSaved(resp);
          setDraft(resp.settings);
          setSaved(true);
          return;
        } catch (err) {
          if (err instanceof ApiError && err.status === 401 && attempt === 0) {
            admin.clear();
            continue;
          }
          throw err;
        }
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Saving failed");
    } finally {
      setSaving(false);
    }
  };

  const stale = collections.filter((c) => c.stale || reindexed.has(c.id));

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Pipeline settings"
      footer={
        <div className="space-y-3">
          {error && <ErrorNote message={error} />}
          {saved && !dirty && (
            <div role="status" className="flex items-center gap-2 text-sm text-accent">
              <CheckCircle2 className="size-4" /> Saved. Query-time settings apply to your next question.
            </div>
          )}
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => draft && setDraft({ ...DEFAULTS })} disabled={!draft}>
              <RotateCcw className="size-3.5" /> Defaults
            </Button>
            <div className="flex-1" />
            <Button variant="primary" onClick={save} loading={saving} disabled={!dirty || overlapInvalid}>
              {!admin.isAuthenticated && <Lock className="size-3.5" />} Save
            </Button>
          </div>
        </div>
      }
    >
      {!draft || !data ? (
        <div className="space-y-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : (
        <div className="space-y-6">
          <Group title="Chunking" note="Changing these marks existing indexes stale until you re-index.">
            <SliderField
              label="Chunk size"
              unit="chars"
              value={draft.chunk_size}
              min={200}
              max={4000}
              step={50}
              onChange={(v) => set("chunk_size", v)}
              index
              explain="Maximum characters per chunk. Small chunks match precisely but carry little context. Large chunks carry more context but their vectors get blurrier."
            />
            <SliderField
              label="Chunk overlap"
              unit="chars"
              value={draft.chunk_overlap}
              min={0}
              max={Math.max(0, draft.chunk_size - 10)}
              step={10}
              onChange={(v) => set("chunk_overlap", v)}
              index
              explain="Characters repeated between neighbouring chunks, so a sentence cut at a boundary still appears whole in one of them. Must be smaller than the chunk size."
              error={overlapInvalid ? "Overlap must be smaller than chunk size" : undefined}
            />
            <ToggleField
              label="Heading-aware chunking"
              checked={draft.heading_aware_chunking}
              onChange={(v) => set("heading_aware_chunking", v)}
              index
              explain="Split at headings first (Markdown #, numbered '2.1 …', ALL CAPS lines), then by size. A chunk never mixes two topics."
            />
          </Group>

          <Group title="Retrieval" note="These apply to the next question; no re-index needed.">
            <SliderField
              label="Chunks to retrieve (k)"
              value={draft.retrieval_k}
              min={1}
              max={20}
              step={1}
              onChange={(v) => set("retrieval_k", v)}
              explain="How many chunks go into the prompt. Too few can miss the answer; too many add noise and cost tokens."
            />
            <SliderField
              label="Minimum relevance"
              unit={draft.min_relevance === 0 ? "off" : undefined}
              value={draft.min_relevance}
              min={0}
              max={0.95}
              step={0.05}
              onChange={(v) => set("min_relevance", Math.round(v * 100) / 100)}
              explain="Chunks whose relevance is below this are dropped, so an off-topic question gets fewer chunks, or none, and the LLM is not called. It is the same relevance number shown next to each source. 0 = off. Around 0.2-0.5 is a typical starting point."
            />
            <ToggleField
              label="Hybrid search (vector + BM25)"
              checked={draft.hybrid_search}
              onChange={(v) => set("hybrid_search", v)}
              explain="Also run keyword search and merge both rankings. Helps with exact terms like codes, names and error numbers."
            />
            <ToggleField
              label="Reranker (cross-encoder)"
              checked={draft.reranker}
              onChange={(v) => set("reranker", v)}
              explain="Fetch a larger pool, then let a small local model read question + chunk together and re-order them. More accurate, a bit slower."
              extra={<RerankerState state={data.reranker.state} error={data.reranker.error} enabled={draft.reranker} />}
            />
            <ToggleField
              label="Rewrite follow-up questions"
              checked={draft.query_rewrite}
              onChange={(v) => set("query_rewrite", v)}
              explain='Before searching, ask the LLM to turn "and how much does it cost?" into a standalone question using the conversation.'
            />
          </Group>

          {indexDirty && (
            <div className="rounded-lg border border-warn/30 bg-warn-soft px-3 py-2.5 text-sm text-warn">
              Saving these chunk settings marks {collections.length ? "your collections" : "collections"} as stale. Chat keeps using the old index until you re-index.
            </div>
          )}

          {stale.length > 0 && (
            <Group title="Re-index" note="Indexes built with different chunk settings or embedding model.">
              <ul className="space-y-2">
                {stale.map((c) => (
                  <ReindexRow
                    key={c.id}
                    collection={c}
                    jobId={reindexed.has(c.id) ? (jobs[c.id] ?? c.active_job_id) : c.active_job_id}
                    onReindex={async () => {
                      await onReindex(c.id);
                      setReindexed((prev) => new Set(prev).add(c.id));
                    }}
                  />
                ))}
              </ul>
            </Group>
          )}

          <p className="font-mono text-[11px] text-muted">embedding model · {data.embedding_model}</p>
        </div>
      )}
    </Drawer>
  );
}

function Group({ title, note, children }: { title: string; note: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="font-display text-sm font-semibold">{title}</h3>
      <p className="mb-3 text-xs text-muted">{note}</p>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function ImpactBadge({ index }: { index?: boolean }) {
  return index ? <Badge tone="warn">re-index</Badge> : <Badge tone="accent">instant</Badge>;
}

function SliderField({
  label,
  unit,
  value,
  min,
  max,
  step,
  onChange,
  explain,
  index,
  error,
}: {
  label: string;
  unit?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  explain: string;
  index?: boolean;
  error?: string;
}) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <div className="rounded-xl border border-line bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <ImpactBadge index={index} />
      </div>
      <div className="mt-2 flex items-center gap-3">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={step}
          value={Math.min(value, max)}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 flex-1 cursor-pointer accent-[var(--accent)]"
        />
        <div className="flex items-center gap-1">
          <input
            type="number"
            aria-label={`${label} value`}
            min={min}
            max={max}
            step={step}
            value={value}
            onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
            className={cx("h-8 w-20 rounded-md border bg-panel px-2 text-right font-mono text-sm outline-none focus:border-accent", error ? "border-danger" : "border-line")}
          />
          {unit && <span className="w-9 font-mono text-[11px] text-muted">{unit}</span>}
        </div>
      </div>
      {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
      <p className="mt-2 text-xs leading-relaxed text-muted">{explain}</p>
    </div>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
  explain,
  index,
  extra,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  explain: string;
  index?: boolean;
  extra?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-line bg-card p-3">
      <div className="flex items-center gap-3">
        <span className="flex-1 text-sm font-medium">{label}</span>
        <ImpactBadge index={index} />
        <Toggle checked={checked} onChange={onChange} label={label} />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted">{explain}</p>
      {extra}
    </div>
  );
}

function RerankerState({ state, error, enabled }: { state: string; error: string | null; enabled: boolean }) {
  if (!enabled && state === "not_loaded") return <p className="mt-2 font-mono text-[11px] text-muted">Model downloads (~90 MB) the first time you enable it.</p>;
  const text = { not_loaded: "model not loaded yet", loading: "downloading / loading model…", ready: "model ready", error: error ?? "model failed to load" }[state];
  return <p className={cx("mt-2 font-mono text-[11px]", state === "error" ? "text-danger" : state === "ready" ? "text-accent" : "text-muted")}>{text}</p>;
}

function ReindexRow({ collection, jobId, onReindex }: { collection: CollectionSummary; jobId: string | null; onReindex: () => Promise<void> }) {
  const { snapshot } = useJobStream(jobId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = !!snapshot && snapshot.stage !== "done" && snapshot.stage !== "error";
  const pct = snapshot ? (snapshot.stage === "done" ? 1 : snapshot.stage === "embedding" ? 0.35 + (snapshot.stats.embedding_pct / 100) * 0.55 : snapshot.stage === "indexing" ? 0.92 : 0.15) : 0;
  return (
    <li className="rounded-xl border border-line bg-card p-3">
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{collection.name}</div>
          <div className="truncate text-xs text-muted">{collection.stale_reasons.join(" · ")}</div>
        </div>
        <Button
          size="sm"
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await onReindex();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Could not start re-index");
            } finally {
              setBusy(false);
            }
          }}
          loading={busy}
          disabled={running}
        >
          <RefreshCw className="size-3.5" /> Re-index
        </Button>
      </div>
      {snapshot && (
        <div className="mt-2">
          <Meter value={pct} colorClass={snapshot.stage === "error" ? "bg-danger" : "bg-accent"} />
          <div className="mt-1 font-mono text-[11px] text-muted">{snapshot.error ?? snapshot.message}</div>
        </div>
      )}
      {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
    </li>
  );
}
