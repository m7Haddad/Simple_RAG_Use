// Sidebar: logo, knowledge base list, LLM status, and the theme and settings buttons.

import { Popover, PopoverButton, PopoverPanel } from "@headlessui/react";
import { Database, Loader2, Moon, Plus, RefreshCw, Settings2, Sun } from "lucide-react";
import { fmtInt } from "../lib/format";
import type { CollectionSummary, LlmHealth } from "../lib/types";
import { Badge, Button, cx, IconButton, Skeleton } from "./ui";

export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="8" className="fill-ink" />
        <rect x="7" y="8" width="18" height="4" rx="2" className="fill-index" />
        <rect x="7" y="14" width="13" height="4" rx="2" className="fill-split" />
        <rect x="7" y="20" width="8" height="4" rx="2" className="fill-load" />
      </svg>
      <div className="leading-tight">
        <div className="font-display text-[17px] font-semibold tracking-tight">RAG Studio</div>
        <div className="font-mono text-[10px] tracking-widest text-muted uppercase">local pipeline lab</div>
      </div>
    </div>
  );
}

export function Sidebar({
  collections,
  collectionsError,
  selectedId,
  onSelect,
  onNew,
  onOpenSettings,
  dark,
  onToggleTheme,
  llm,
}: {
  collections: CollectionSummary[] | null;
  collectionsError: string | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onOpenSettings: () => void;
  dark: boolean;
  onToggleTheme: () => void;
  llm: { health: LlmHealth | null; error: string | null; checking: boolean; recheck: () => void };
}) {
  return (
    <nav aria-label="Knowledge bases" className="flex h-full flex-col bg-panel">
      <div className="px-4 pt-5 pb-4">
        <Logo />
      </div>
      <div className="px-3">
        <Button variant="primary" className="w-full" onClick={onNew}>
          <Plus className="size-4" /> New knowledge base
        </Button>
      </div>

      <div className="mt-5 flex items-center justify-between px-4 pb-2">
        <span className="font-mono text-[11px] tracking-widest text-muted uppercase">Collections</span>
        {collections && <span className="font-mono text-[11px] text-muted">{collections.length}</span>}
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto px-2 pb-3">
        {collectionsError && <p className="px-2 text-sm text-danger">{collectionsError}</p>}
        {!collections && !collectionsError && (
          <div className="space-y-2 px-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        )}
        {collections?.length === 0 && (
          <p className="px-3 py-2 text-sm text-muted">No knowledge bases yet. Create one from your documents to start.</p>
        )}
        <ul className="space-y-0.5">
          {collections?.map((c) => (
            <li key={c.id}>
              <button
                onClick={() => onSelect(c.id)}
                aria-current={c.id === selectedId ? "page" : undefined}
                className={cx(
                  "group w-full rounded-lg px-3 py-2 text-left transition",
                  c.id === selectedId ? "bg-card shadow-sm ring-1 ring-line" : "hover:bg-sunken",
                )}
              >
                <div className="flex items-center gap-2">
                  <Database className={cx("size-3.5 shrink-0", c.id === selectedId ? "text-accent" : "text-muted")} />
                  <span className="truncate text-sm font-medium">{c.name}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 pl-5.5">
                  <span className="font-mono text-[11px] text-muted">
                    {fmtInt(c.chunk_count)} chunks · {c.source_count} src
                  </span>
                  {c.active_job_id && (
                    <Badge tone="info">
                      <Loader2 className="size-3 animate-spin" /> working
                    </Badge>
                  )}
                  {c.stale && !c.active_job_id && (
                    <Badge tone="warn" title={`Index built with different settings: ${c.stale_reasons.join(", ")}`}>
                      stale index
                    </Badge>
                  )}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2 border-t border-line p-3">
        <LlmStatus {...llm} />
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" className="flex-1 justify-start" onClick={onOpenSettings}>
            <Settings2 className="size-4" /> Settings
          </Button>
          <IconButton label={dark ? "Switch to light mode" : "Switch to dark mode"} onClick={onToggleTheme}>
            {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </IconButton>
        </div>
      </div>
    </nav>
  );
}

function LlmStatus({ health, error, checking, recheck }: { health: LlmHealth | null; error: string | null; checking: boolean; recheck: () => void }) {
  const state = error ? "down" : !health ? "checking" : health.ok ? "ok" : "down";
  const dot = { ok: "bg-index", down: "bg-danger", checking: "bg-muted" }[state];
  return (
    <Popover className="relative">
      <PopoverButton className="flex w-full items-center gap-2.5 rounded-lg border border-line bg-card px-3 py-2 text-left transition hover:border-line-strong">
        <span className="relative flex size-2.5 shrink-0">
          {state === "ok" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-index opacity-40" />}
          <span className={cx("relative inline-flex size-2.5 rounded-full", dot)} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[10px] tracking-widest text-muted uppercase">
            LLM · {health?.provider ?? "…"} {state === "down" ? "· error" : state === "ok" ? "· ready" : ""}
          </span>
          <span className="block truncate text-[13px]">{health?.model ?? (error ? "backend offline" : "checking…")}</span>
        </span>
      </PopoverButton>
      <PopoverPanel anchor={{ to: "top start", gap: 8 }} className="z-50 w-80 rounded-xl border border-line bg-panel p-4 text-sm shadow-xl">
        <div className="mb-2 font-display font-semibold">{state === "ok" ? "LLM is reachable" : state === "down" ? "LLM problem" : "Checking LLM…"}</div>
        {error && <p className="text-danger">{error}</p>}
        {health && (
          <dl className="space-y-1 font-mono text-xs">
            <Row k="provider" v={health.provider} />
            <Row k="base url" v={health.base_url} />
            <Row k="model" v={health.model} />
            {health.latency_ms !== null && <Row k="test call" v={`${Math.round(health.latency_ms)} ms`} />}
          </dl>
        )}
        {health?.error && <p className="mt-3 text-danger">{health.error}</p>}
        {health?.hint && <p className="mt-1 text-ink-2">{health.hint}</p>}
        {!!health?.suggestions.length && (
          <div className="mt-2">
            <div className="text-xs text-muted">Did you mean:</div>
            <ul className="mt-1 space-y-0.5 font-mono text-xs">
              {health.suggestions.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}
        <Button size="sm" className="mt-3 w-full" onClick={recheck} loading={checking}>
          <RefreshCw className="size-3.5" /> Check again
        </Button>
      </PopoverPanel>
    </Popover>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-muted">{k}</dt>
      <dd className="min-w-0 break-all">{v}</dd>
    </div>
  );
}
