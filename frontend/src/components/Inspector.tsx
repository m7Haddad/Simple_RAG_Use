// Pipeline Inspector (Lab mode): the search query, retrieved chunks, exact prompt and timings of one answer.

import { ArrowDown, ChevronDown, ChevronRight, FlaskConical, Maximize2, Minimize2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { estimateTokens, fmtInt, fmtMs } from "../lib/format";
import type { AssistantMessage, RetrievedChunk, Timings } from "../lib/types";
import { relevanceTone } from "./SourcesList";
import { Badge, CopyButton, cx, Skeleton } from "./ui";

export function Inspector({ message }: { message: AssistantMessage | null }) {
  if (!message) {
    return (
      <div className="flex h-full flex-col items-center justify-center px-8 text-center">
        <FlaskConical className="size-8 text-muted" />
        <p className="mt-3 font-display font-semibold">Nothing to inspect yet</p>
        <p className="mt-1 text-sm text-muted">
          Ask a question. This panel then shows every step: the search query, the chunks retrieved and how close each was, the exact
          prompt the LLM received, and where the time went.
        </p>
      </div>
    );
  }
  const waiting = message.status === "streaming";
  return (
    <div className="space-y-4 p-4">
      <div>
        <div className="font-mono text-[10px] tracking-widest text-muted uppercase">Inspecting</div>
        <p className="mt-0.5 line-clamp-2 text-sm font-medium">“{message.question}”</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge>k = {message.settings.k}</Badge>
          <Badge tone={message.settings.hybrid ? "info" : "neutral"}>hybrid {message.settings.hybrid ? "on" : "off"}</Badge>
          <Badge tone={message.settings.reranker ? "info" : "neutral"}>rerank {message.settings.reranker ? "on" : "off"}</Badge>
          <Badge tone={message.settings.rewrite ? "info" : "neutral"}>rewrite {message.settings.rewrite ? "on" : "off"}</Badge>
        </div>
      </div>

      <Step n={1} title="Search query" color="text-load" hint="What we actually searched for.">
        {message.rewrite ? (
          <div className="space-y-1.5 text-sm">
            <div className="rounded-md bg-sunken px-2.5 py-1.5 text-ink-2">{message.rewrite.original}</div>
            <div className="flex items-center gap-1.5 pl-1 font-mono text-[11px] text-muted">
              <ArrowDown className="size-3" /> rewritten by the LLM into a standalone question · {fmtMs(message.rewrite.ms)}
            </div>
            <div className="rounded-md border border-load/40 bg-card px-2.5 py-1.5">{message.rewrite.rewritten}</div>
          </div>
        ) : message.sources ? (
          <div className="text-sm">
            <div className="rounded-md bg-sunken px-2.5 py-1.5">{message.sources.query}</div>
            <p className="mt-1.5 text-xs text-muted">
              {message.settings.rewrite
                ? "First question in this chat, so there was nothing to rewrite: searched as typed."
                : "Query rewriting is off: searched exactly as typed."}
            </p>
          </div>
        ) : (
          <Skeleton className="h-8" />
        )}
      </Step>

      <Step
        n={2}
        title="Retrieved chunks"
        color="text-index"
        hint="Ranked best first. Distance is cosine distance between question and chunk vectors: 0 = same meaning, 1 = unrelated."
      >
        {message.sources ? <Retrieved chunks={message.sources.chunks} mode={message.sources.mode} dropped={message.sources.dropped ?? 0} /> : waiting ? <Skeleton className="h-24" /> : <Empty />}
      </Step>

      <Step n={3} title="Prompt sent to the LLM" color="text-split" hint="Exactly what the model read: rules, numbered context, recent history, your question.">
        {message.prompt ? <PromptView text={message.prompt.text} messages={message.prompt.messages.length} /> : waiting ? <Skeleton className="h-24" /> : <Empty />}
      </Step>

      <Step n={4} title="Timings" color="text-gen" hint="Where the time went for this answer.">
        {message.timings ? <Waterfall t={message.timings} /> : waiting ? <Skeleton className="h-16" /> : <Empty />}
      </Step>
    </div>
  );
}

function Empty() {
  return <p className="text-sm text-muted">Not available for this answer.</p>;
}

function Step({ n, title, color, hint, children }: { n: number; title: string; color: string; hint: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-panel">
      <header className="flex items-start gap-2.5 border-b border-line px-3 py-2.5">
        <span className={cx("mt-px flex size-5 shrink-0 items-center justify-center rounded-full border border-current font-mono text-[11px]", color)}>{n}</span>
        <div>
          <h3 className="font-display text-sm font-semibold">{title}</h3>
          <p className="text-xs text-muted">{hint}</p>
        </div>
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}

function Retrieved({ chunks, mode, dropped }: { chunks: RetrievedChunk[]; mode: string; dropped: number }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!chunks.length) {
    return (
      <p className="text-sm text-muted">
        {dropped
          ? `No chunk was close enough: ${dropped} candidate${dropped === 1 ? " was" : "s were"} below the minimum relevance setting, so the LLM was not called.`
          : "No chunks found. The index is empty, so the LLM was not called."}
      </p>
    );
  }
  const hybrid = mode.includes("hybrid");
  const rerank = mode.includes("rerank");
  const maxD = Math.max(1, ...chunks.map((c) => c.distance ?? 0));
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-xs text-muted">
        <span>mode</span>
        <Badge tone="accent">{mode}</Badge>
        <span>· {chunks.length} kept</span>
        {dropped > 0 && <span>· {dropped} dropped (below min relevance)</span>}
      </div>

      {/* Distance strip: where each chunk sits between "same meaning" and "unrelated". */}
      <div className="mb-4 px-1">
        <div className="relative h-7">
          <div className="absolute top-1/2 right-0 left-0 h-px bg-line-strong" />
          {chunks.map((c) => (
            <span
              key={c.chunk_id}
              title={`#${c.rank} · distance ${c.distance?.toFixed(3) ?? "n/a"}`}
              className={cx("absolute top-1/2 flex size-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full font-mono text-[9px] font-semibold text-white ring-2 ring-panel dark:text-black", relevanceTone(c.relevance))}
              style={{ left: `${((c.distance ?? maxD) / maxD) * 100}%`, zIndex: 100 - c.rank }}
            >
              {c.rank}
            </span>
          ))}
        </div>
        <div className="flex justify-between font-mono text-[10px] text-muted">
          <span>0 · identical</span>
          <span>distance →</span>
          <span>{maxD.toFixed(maxD > 1 ? 2 : 0)} · unrelated</span>
        </div>
      </div>

      <ol className="divide-y divide-line overflow-hidden rounded-lg border border-line bg-card">
        {chunks.map((c) => (
          <li key={c.chunk_id}>
            <button onClick={() => setOpen(open === c.chunk_id ? null : c.chunk_id)} aria-expanded={open === c.chunk_id} className="w-full px-2.5 py-2 text-left hover:bg-sunken">
              <div className="flex items-center gap-2">
                <span className="w-5 shrink-0 font-mono text-xs font-semibold text-ink-2">#{c.rank}</span>
                <span className="min-w-0 flex-1 truncate text-[13px]">
                  {c.source_name} <span className="text-muted">· {c.location}</span>
                </span>
                <span className="font-mono text-xs tabular-nums">{c.distance?.toFixed(3) ?? "–"}</span>
                {open === c.chunk_id ? <ChevronDown className="size-3.5 text-muted" /> : <ChevronRight className="size-3.5 text-muted" />}
              </div>
              {(hybrid || rerank) && (
                <div className="mt-1 flex gap-3 pl-7 font-mono text-[10px] text-muted">
                  <span>vector #{c.vector_rank ?? "–"}</span>
                  {hybrid && <span>bm25 #{c.bm25_rank ?? "–"}</span>}
                  {rerank && <span>rerank {c.rerank_score?.toFixed(2) ?? "–"}</span>}
                </div>
              )}
            </button>
            {open === c.chunk_id && (
              <div className="border-t border-line bg-panel px-2.5 py-2">
                <div className="mb-1 font-mono text-[10px] text-muted">
                  chunk #{c.chunk_id} · {c.chars} chars{c.heading ? ` · § ${c.heading}` : ""}
                </div>
                <p className="scroll-thin max-h-56 overflow-y-auto font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">{c.text}</p>
              </div>
            )}
          </li>
        ))}
      </ol>
      {(hybrid || rerank) && (
        <p className="mt-2 text-xs text-muted">
          {hybrid && "Hybrid merges vector and keyword (BM25) rankings with Reciprocal Rank Fusion. "}
          {rerank && "The cross-encoder re-ordered the candidates; a higher rerank score means more relevant."}
        </p>
      )}
    </div>
  );
}

function PromptView({ text, messages }: { text: string; messages: number }) {
  const [expanded, setExpanded] = useState(false);
  const parts = text.split(/(===== [A-Z]+ =====)/g);
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 font-mono text-[11px] text-muted">
        <span>{messages} messages</span>
        <span>· {fmtInt(text.length)} chars</span>
        <span>· ≈{fmtInt(estimateTokens(text))} tokens</span>
        <span className="ml-auto flex items-center">
          <CopyButton text={text} />
          <button
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs hover:bg-sunken hover:text-ink"
            aria-label={expanded ? "Collapse prompt" : "Expand prompt"}
          >
            {expanded ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
          </button>
        </span>
      </div>
      <pre className={cx("scroll-thin overflow-auto rounded-lg border border-line bg-card p-2.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap", expanded ? "max-h-[70vh]" : "max-h-72")}>
        {parts.map((part, i) =>
          /^===== [A-Z]+ =====$/.test(part) ? (
            <span key={i} className={cx("font-semibold", part.includes("SYSTEM") ? "text-split" : part.includes("ASSISTANT") ? "text-embed" : "text-load")}>
              {part}
            </span>
          ) : (
            <span key={i}>
              {part.split(/^(\[\d+\] .+)$/gm).map((piece, j) =>
                j % 2 === 1 ? (
                  <span key={j} className="font-semibold text-index">
                    {piece}
                  </span>
                ) : (
                  piece
                ),
              )}
            </span>
          ),
        )}
      </pre>
    </div>
  );
}

const SEGMENTS: { key: keyof Timings; label: string; color: string }[] = [
  { key: "rewrite_ms", label: "Rewrite query (LLM)", color: "bg-load" },
  { key: "embed_ms", label: "Embed question", color: "bg-embed" },
  { key: "search_ms", label: "Vector search", color: "bg-index" },
  { key: "bm25_ms", label: "Keyword search + fusion", color: "bg-index" },
  { key: "rerank_ms", label: "Rerank (cross-encoder)", color: "bg-split" },
  { key: "ttft_ms", label: "Wait for first token", color: "bg-gen" },
];

function Waterfall({ t }: { t: Timings }) {
  const rows: { label: string; start: number; ms: number; color: string }[] = [];
  let cursor = 0;
  for (const seg of SEGMENTS) {
    const ms = t[seg.key];
    if (ms === undefined) continue;
    rows.push({ label: seg.label, start: cursor, ms, color: seg.color });
    cursor += ms;
  }
  if (t.generation_ms !== undefined) {
    const streaming = Math.max(0, t.generation_ms - (t.ttft_ms ?? 0));
    rows.push({ label: "Stream the answer", start: cursor, ms: streaming, color: "bg-gen/60" });
    cursor += streaming;
  }
  const total = Math.max(t.total_ms ?? cursor, cursor, 1);
  return (
    <div>
      <ul className="space-y-1.5">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[9.5rem_1fr_3.75rem] items-center gap-2 text-xs">
            <span className="truncate text-ink-2">{r.label}</span>
            <span className="relative h-2.5 rounded-sm bg-sunken">
              <span className={cx("absolute inset-y-0 rounded-sm", r.color)} style={{ left: `${(r.start / total) * 100}%`, width: `max(2px, ${(r.ms / total) * 100}%)` }} />
            </span>
            <span className="text-right font-mono tabular-nums">{fmtMs(r.ms)}</span>
          </li>
        ))}
      </ul>
      <div className="mt-2.5 flex justify-between border-t border-line pt-2 font-mono text-xs">
        <span className="text-muted">retrieval {fmtMs(t.retrieval_ms)}</span>
        <span>total {fmtMs(t.total_ms)}</span>
      </div>
    </div>
  );
}
