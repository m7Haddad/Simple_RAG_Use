// Live view of an ingest or re-index job: its stages, stats and sample chunks.

import { AlertTriangle, Check, ChevronRight, FileText, Globe, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fmtChars, fmtInt, fmtSeconds } from "../lib/format";
import type { JobSnapshot, JobSource, JobStage } from "../lib/types";
import { Badge, cx, Skeleton } from "./ui";

const STAGES = [
  { key: "loading", label: "Load", color: "text-load", bg: "bg-load", explain: "Extracting text from each source, one record per page or section." },
  { key: "splitting", label: "Split", color: "text-split", bg: "bg-split", explain: "Cutting pages into overlapping chunks that are small enough to search precisely." },
  { key: "embedding", label: "Embed", color: "text-embed", bg: "bg-embed", explain: "Turning every chunk into a vector (a list of numbers that captures meaning) with the local model." },
  { key: "indexing", label: "Index", color: "text-index", bg: "bg-index", explain: "Writing vectors to Chroma on disk, so they survive restarts without re-embedding." },
] as const;

type StageKey = (typeof STAGES)[number]["key"];
const ORDER: Record<string, number> = { queued: -1, loading: 0, splitting: 1, embedding: 2, indexing: 3, done: 4 };

function progressOf(s: JobSnapshot): number {
  const { stats } = s;
  const loaded = s.sources.filter((x) => x.status !== "pending" && x.status !== "loading").length;
  switch (s.stage) {
    case "queued":
      return 0;
    case "loading":
      return (loaded / Math.max(1, s.sources.length)) * 25;
    case "splitting":
      return 30;
    case "embedding":
      return 35 + stats.embedding_pct * 0.55;
    case "indexing":
      return 90 + (stats.indexed / Math.max(1, stats.chunks)) * 10;
    case "done":
      return 100;
    default:
      return 0;
  }
}

export function PipelineView({ snapshot, chunkSize, title }: { snapshot: JobSnapshot | null; chunkSize?: number; title?: string }) {
  const lastActive = useRef<StageKey>("loading");
  if (snapshot && snapshot.stage in ORDER && snapshot.stage !== "done" && snapshot.stage !== "queued") {
    lastActive.current = snapshot.stage as StageKey;
  }

  if (!snapshot) {
    return (
      <section className="rounded-2xl border border-line bg-card p-5">
        <Skeleton className="mb-6 h-4 w-40" />
        <Skeleton className="h-16" />
        <Skeleton className="mt-6 h-2" />
      </section>
    );
  }

  const failed = snapshot.stage === "error";
  const current = failed ? ORDER[lastActive.current] : ORDER[snapshot.stage];
  const pct = failed ? progressOf({ ...snapshot, stage: lastActive.current as JobStage }) : progressOf(snapshot);
  const running = !failed && snapshot.stage !== "done";
  const activeStage = STAGES[Math.max(0, Math.min(3, current))];

  return (
    <section aria-label="Indexing pipeline" className="overflow-hidden rounded-2xl border border-line bg-card">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] tracking-widest text-muted uppercase">
            {snapshot.kind === "reindex" ? "Re-index" : "Ingest"} pipeline
          </span>
          {title && <span className="text-sm font-medium">· {title}</span>}
        </div>
        <div className="flex items-center gap-2">
          {snapshot.stage === "done" && <Badge tone="accent"><Check className="size-3" /> complete</Badge>}
          {failed && <Badge tone="danger"><X className="size-3" /> failed</Badge>}
          {snapshot.stage === "queued" && <Badge>queued</Badge>}
          <span className="font-mono text-xs text-muted tabular-nums">{fmtSeconds(snapshot.elapsed_s)}</span>
        </div>
      </header>

      <div className="lab-grid px-5 pt-6 pb-5">
        <ol className="grid grid-cols-4 gap-0" aria-label="Pipeline stages">
          {STAGES.map((stage, i) => {
            const state = failed && i === current ? "error" : i < current || snapshot.stage === "done" ? "done" : i === current ? "active" : "pending";
            return (
              <li key={stage.key} className="relative flex flex-col items-center text-center" aria-current={state === "active" ? "step" : undefined}>
                {i > 0 && (
                  <div
                    aria-hidden
                    className={cx("absolute top-[19px] h-0.5", state === "pending" ? "text-line-strong" : stage.color)}
                    style={{ left: "calc(-50% + 26px)", right: "calc(50% + 26px)" }}
                  >
                    <div className={cx("h-full w-full", state === "active" && running ? "flowing" : "bg-current")} />
                  </div>
                )}
                <div
                  className={cx(
                    "relative z-10 flex size-10 items-center justify-center rounded-full border-2 font-mono text-sm font-medium transition",
                    state === "done" && cx("border-transparent text-white dark:text-black", stage.bg),
                    state === "active" && cx("border-current bg-card", stage.color, running && "pulse-ring"),
                    state === "pending" && "border-line-strong bg-card text-muted",
                    state === "error" && "border-danger bg-danger-soft text-danger",
                  )}
                >
                  {state === "done" ? <Check className="size-4" /> : state === "error" ? <X className="size-4" /> : state === "active" && running ? <Loader2 className="size-4 animate-spin" /> : i + 1}
                </div>
                <div className={cx("mt-2 font-display text-sm font-semibold", state === "pending" ? "text-muted" : "text-ink")}>{stage.label}</div>
                <div className="mt-0.5 font-mono text-[11px] text-muted tabular-nums">{stageStat(stage.key, snapshot)}</div>
              </li>
            );
          })}
        </ol>

        <div className="mt-6">
          <div className="h-2 overflow-hidden rounded-full bg-sunken">
            <div
              className={cx("h-full rounded-full transition-[width] duration-500", failed ? "bg-danger" : activeStage.bg)}
              style={{ width: `${Math.round(pct)}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between gap-3 text-sm">
            <span className={cx("min-w-0 truncate", failed ? "text-danger" : "text-ink-2")}>{snapshot.error ?? snapshot.message}</span>
            <span className="font-mono text-xs text-muted tabular-nums">{Math.round(pct)}%</span>
          </div>
          {running && <p className="mt-1 text-xs text-muted">{activeStage.explain}</p>}
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-px border-t border-line bg-line sm:grid-cols-5">
        <Stat label="Pages" value={fmtInt(snapshot.stats.pages)} color="text-load" />
        <Stat label="Characters" value={fmtChars(snapshot.stats.characters)} color="text-load" />
        <Stat label="Chunks" value={fmtInt(snapshot.stats.chunks)} color="text-split" />
        <Stat label="Embedded" value={`${Math.round(snapshot.stats.embedding_pct)}%`} color="text-embed" />
        <Stat label="Elapsed" value={fmtSeconds(snapshot.elapsed_s)} color="text-ink" className="col-span-2 sm:col-span-1" />
      </dl>

      <SourcesStatus sources={snapshot.sources} />
      <SampleChunks snapshot={snapshot} chunkSize={chunkSize} />
    </section>
  );
}

function stageStat(key: StageKey, s: JobSnapshot): string {
  const { stats } = s;
  const reached = ORDER[s.stage] >= ORDER[key] || s.stage === "error";
  if (!reached) return "—";
  switch (key) {
    case "loading":
      return `${fmtInt(stats.pages)} pages`;
    case "splitting":
      return `${fmtInt(stats.chunks)} chunks`;
    case "embedding":
      return `${Math.round(stats.embedding_pct)}%`;
    case "indexing":
      return `${fmtInt(stats.indexed)} stored`;
  }
}

function Stat({ label, value, color, className }: { label: string; value: string; color: string; className?: string }) {
  return (
    <div className={cx("bg-card px-4 py-3", className)}>
      <dt className="font-mono text-[10px] tracking-widest text-muted uppercase">{label}</dt>
      <dd className={cx("mt-0.5 font-display text-xl font-semibold tabular-nums", color)}>{value}</dd>
    </div>
  );
}

const SOURCE_TONE: Record<JobSource["status"], "neutral" | "info" | "accent" | "danger"> = {
  pending: "neutral",
  loading: "info",
  loaded: "info",
  indexed: "accent",
  error: "danger",
};

function SourcesStatus({ sources }: { sources: JobSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="border-t border-line">
      <div className="px-5 pt-3 pb-1 font-mono text-[11px] tracking-widest text-muted uppercase">Sources</div>
      <ul className="divide-y divide-line">
        {sources.map((s) => (
          <li key={s.source_id} className="px-5 py-2.5">
            <div className="flex items-center gap-2.5 text-sm">
              {s.kind === "url" ? <Globe className="size-4 shrink-0 text-embed" /> : <FileText className="size-4 shrink-0 text-load" />}
              <span className="min-w-0 flex-1 truncate">{s.name}</span>
              {s.status !== "pending" && s.status !== "error" && (
                <span className="hidden font-mono text-[11px] text-muted sm:inline">
                  {s.pages} pg · {fmtChars(s.characters)} ch{s.chunks ? ` · ${s.chunks} chunks` : ""}
                </span>
              )}
              <Badge tone={SOURCE_TONE[s.status]}>
                {s.status === "loading" && <Loader2 className="size-3 animate-spin" />}
                {s.status}
              </Badge>
            </div>
            {s.error && (
              <div className="mt-1.5 flex items-start gap-1.5 pl-6.5 text-xs text-danger">
                <AlertTriangle className="mt-px size-3.5 shrink-0" /> {s.error}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SampleChunks({ snapshot, chunkSize }: { snapshot: JobSnapshot; chunkSize?: number }) {
  const [open, setOpen] = useState(false);
  const hasSamples = snapshot.sample_chunks.length > 0;
  useEffect(() => {
    if (hasSamples && snapshot.stage !== "done") setOpen(true);
  }, [hasSamples, snapshot.stage]);
  if (!hasSamples) return null;
  return (
    <div className="border-t border-line">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-5 py-3 text-left text-sm font-medium hover:bg-sunken"
      >
        <ChevronRight className={cx("size-4 transition", open && "rotate-90")} />
        Sample chunks <span className="font-mono text-xs text-muted">first {snapshot.sample_chunks.length} of {snapshot.stats.chunks}</span>
        <span className="ml-auto hidden text-xs font-normal text-muted sm:inline">what the splitter produced</span>
      </button>
      {open && (
        <ol className="space-y-2.5 px-5 pb-5">
          {snapshot.sample_chunks.map((c) => (
            <li key={c.chunk_id} className="rounded-lg border border-line border-l-split bg-panel py-2 pr-3 pl-3 [border-left-width:3px]">
              <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-muted">
                <span className="text-split">chunk #{c.chunk_id}</span>
                <span>{c.source_name}</span>
                <span>· {c.location}</span>
                {c.heading && <span>· § {c.heading}</span>}
                <span className="ml-auto tabular-nums">{c.chars} chars</span>
              </div>
              {chunkSize && (
                <div className="mb-1.5 h-1 overflow-hidden rounded-full bg-sunken" title={`${c.chars} of max ${chunkSize} characters`}>
                  <div className="h-full bg-split" style={{ width: `${Math.min(100, (c.chars / chunkSize) * 100)}%` }} />
                </div>
              )}
              <p className="font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-2">
                {c.text}
                {c.chars > c.text.length && <span className="text-muted">…</span>}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
