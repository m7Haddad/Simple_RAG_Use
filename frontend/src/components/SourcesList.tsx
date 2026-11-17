// The list of chunks an answer was built from, with their score bars.

import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { RetrievedChunk } from "../lib/types";
import { cx, Meter } from "./ui";

export function relevanceTone(relevance: number | null) {
  if (relevance === null) return "bg-muted";
  if (relevance >= 0.6) return "bg-index";
  if (relevance >= 0.4) return "bg-split";
  return "bg-gen";
}

export type Highlight = { rank: number; nonce: number } | null;

// One labelled 0..1 score with its fill bar (relevance, hybrid, rerank).
function ScoreBar({ label, value, colorClass, title, wide }: { label: string; value: number | null; colorClass: string; title: string; wide?: boolean }) {
  return (
    <span className={cx("block", wide ? "w-24" : "w-20")} title={title}>
      <span className="flex items-baseline justify-between gap-1.5 font-mono text-[11px]">
        <span className="text-muted">{label}</span>
        <span className="tabular-nums">{value?.toFixed(2) ?? "–"}</span>
      </span>
      <Meter value={value ?? 0} className="mt-1" colorClass={colorClass} />
    </span>
  );
}

export function SourceRow({ chunk, highlight = null }: { chunk: RetrievedChunk; highlight?: Highlight }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLLIElement>(null);
  const highlighted = highlight?.rank === chunk.rank;
  useEffect(() => {
    if (highlight?.rank === chunk.rank) {
      setOpen(true);
      ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlight, chunk.rank]);
  return (
    <li ref={ref} className={cx("rounded-lg border bg-card transition", highlighted ? "border-accent ring-2 ring-accent/25" : "border-line")}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-3 px-3 py-2.5 text-left">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-sunken font-mono text-[11px] font-medium text-ink-2">
          {chunk.rank}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-sm">
            <FileText className="size-3.5 shrink-0 text-load" />
            <span className="truncate font-medium">{chunk.source_name}</span>
            <span className="shrink-0 text-muted">· {chunk.location}</span>
          </span>
          <span className="mt-1 line-clamp-2 block text-[13px] text-ink-2">{chunk.snippet}</span>
        </span>
        <span className="hidden shrink-0 gap-3 sm:flex">
          <ScoreBar
            label="relevance"
            wide
            value={chunk.relevance}
            colorClass={relevanceTone(chunk.relevance)}
            title={`Cosine distance ${chunk.distance ?? "n/a"} (0 = same meaning). Relevance = 1 − distance.`}
          />
          {chunk.hybrid_score != null && (
            <ScoreBar
              label="hybrid"
              value={chunk.hybrid_score}
              colorClass="bg-load"
              title={`Hybrid score: vector rank #${chunk.vector_rank ?? "–"} and keyword (BM25) rank #${chunk.bm25_rank ?? "–"} fused with Reciprocal Rank Fusion. 1.00 = ranked first by both; about 0.50 = found by only one of them.`}
            />
          )}
          {chunk.rerank_relevance != null && (
            <ScoreBar
              label="rerank"
              value={chunk.rerank_relevance}
              colorClass="bg-embed"
              title={`Reranker: the cross-encoder read the question and this chunk together. Raw score ${chunk.rerank_score?.toFixed(2) ?? "n/a"} → probability ${chunk.rerank_relevance.toFixed(2)} that it answers the question. It is usually decisive: near 1 or near 0.`}
            />
          )}
        </span>
        {open ? <ChevronDown className="mt-0.5 size-4 shrink-0 text-muted" /> : <ChevronRight className="mt-0.5 size-4 shrink-0 text-muted" />}
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2.5">
          <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
            <span>chunk #{chunk.chunk_id}</span>
            <span>distance {chunk.distance?.toFixed(4) ?? "–"}</span>
            {chunk.hybrid_score != null && (
              <span>
                vector #{chunk.vector_rank ?? "–"} · bm25 #{chunk.bm25_rank ?? "–"}
              </span>
            )}
            {chunk.rerank_score != null && <span>rerank raw {chunk.rerank_score.toFixed(2)}</span>}
            <span>{chunk.chars} chars</span>
            {chunk.heading && <span>§ {chunk.heading}</span>}
          </div>
          <p className="scroll-thin max-h-64 overflow-y-auto font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-2">{chunk.text}</p>
        </div>
      )}
    </li>
  );
}

export function SourcesList({ chunks, highlight, defaultOpen = false }: { chunks: RetrievedChunk[]; highlight: Highlight; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    if (highlight !== null) setOpen(true);
  }, [highlight]);
  const files = new Set(chunks.map((c) => c.source_name)).size;
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs font-medium text-ink-2 hover:bg-sunken"
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        Sources
        <span className="font-mono text-muted">
          {chunks.length} chunk{chunks.length === 1 ? "" : "s"} · {files} file{files === 1 ? "" : "s"}
        </span>
      </button>
      {open && (
        <ol className="mt-2 space-y-1.5">
          {chunks.map((c) => (
            <SourceRow key={c.chunk_id} chunk={c} highlight={highlight} />
          ))}
        </ol>
      )}
    </div>
  );
}
