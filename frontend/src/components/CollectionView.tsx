// One knowledge base, with its Chat and Index tabs.

import { Menu, MenuButton, MenuItem, MenuItems } from "@headlessui/react";
import { AlertTriangle, ArrowRight, FileText, FlaskConical, Globe, Loader2, MessageSquare, MoreHorizontal, Plus, RefreshCw, Trash2, Layers } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { ChatStore } from "../hooks/useChat";
import { useJobStream } from "../hooks";
import { api, ApiError } from "../lib/api";
import { fmtChars, fmtInt, fmtRelative } from "../lib/format";
import type { CollectionDetail, CollectionSummary, JobStarted, RagSettings } from "../lib/types";
import { ChatView } from "./ChatView";
import { IngestPanel } from "./IngestPanel";
import { PipelineView } from "./PipelineView";
import { Badge, Button, cx, ErrorNote, Modal, Skeleton } from "./ui";

export type Tab = "chat" | "index";

export function CollectionView({
  summary,
  tab,
  onTab,
  jobId,
  onJobStarted,
  onChanged,
  onDeleted,
  onReindex,
  settings,
  store,
  labMode,
  onLabMode,
}: {
  summary: CollectionSummary;
  tab: Tab;
  onTab: (t: Tab) => void;
  jobId: string | null;
  onJobStarted: (started: JobStarted) => void;
  onChanged: () => void;
  onDeleted: () => void;
  onReindex: (id: string) => Promise<void>;
  settings: RagSettings | null;
  store: ChatStore;
  labMode: boolean;
  onLabMode: (on: boolean) => void;
}) {
  const [detail, setDetail] = useState<CollectionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      setDetail(await api.getCollection(summary.id));
      setDetailError(null);
    } catch (err) {
      setDetailError(err instanceof ApiError ? err.message : "Could not load collection");
    }
  }, [summary.id]);

  useEffect(() => {
    setDetail(null);
    setActionError(null);
  }, [summary.id]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail, summary.updated_at, summary.stale]);

  const { snapshot, error: streamError } = useJobStream(jobId, () => {
    onChanged();
    loadDetail();
  });
  const jobRunning = !!snapshot && snapshot.stage !== "done" && snapshot.stage !== "error";

  const reindex = async () => {
    setActionError(null);
    try {
      await onReindex(summary.id);
      onTab("index");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not start re-index");
    }
  };

  const disabledReason = summary.reindex_required
    ? "The embedding model changed since this collection was indexed. Re-index it before chatting."
    : summary.chunk_count === 0
      ? jobRunning || summary.active_job_id
        ? "Indexing in progress. Chat unlocks when the index is built."
        : "No indexed content yet. Add sources in the Index tab."
      : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-line bg-panel/60 px-4 pt-4 sm:px-6">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="truncate font-display text-xl font-semibold tracking-tight sm:text-2xl">{summary.name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
              <span>{fmtInt(summary.chunk_count)} chunks</span>
              <span>{summary.source_count} sources</span>
              {summary.indexed_with && (
                <span title="Settings this index was built with">
                  size {summary.indexed_with.chunk_size} · overlap {summary.indexed_with.chunk_overlap}
                  {summary.indexed_with.heading_aware_chunking ? " · headings" : ""}
                </span>
              )}
              <span>updated {fmtRelative(summary.updated_at)}</span>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant={labMode ? "primary" : "secondary"}
              onClick={() => onLabMode(!labMode)}
              aria-pressed={labMode}
              title="Show the Pipeline Inspector next to the chat"
            >
              <FlaskConical className="size-4" /> <span className="hidden sm:inline">Lab mode</span>
            </Button>
            <Menu>
              <MenuButton className="inline-flex size-8 items-center justify-center rounded-lg border border-line bg-card text-ink-2 hover:bg-sunken" aria-label="Collection actions">
                <MoreHorizontal className="size-4" />
              </MenuButton>
              <MenuItems anchor="bottom end" className="z-50 mt-1 w-52 rounded-xl border border-line bg-panel p-1 shadow-xl focus:outline-none">
                <MenuItem>
                  <button onClick={() => onTab("index")} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm data-focus:bg-sunken">
                    <Plus className="size-4" /> Add sources
                  </button>
                </MenuItem>
                <MenuItem disabled={jobRunning || !summary.source_count}>
                  <button onClick={reindex} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm data-disabled:opacity-40 data-focus:bg-sunken">
                    <RefreshCw className="size-4" /> Re-index now
                  </button>
                </MenuItem>
                <MenuItem disabled={jobRunning}>
                  <button onClick={() => setConfirmDelete(true)} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-danger data-disabled:opacity-40 data-focus:bg-danger-soft">
                    <Trash2 className="size-4" /> Delete
                  </button>
                </MenuItem>
              </MenuItems>
            </Menu>
          </div>
        </div>

        {summary.stale && !jobRunning && (
          <div className={cx("mt-3 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-sm", summary.reindex_required ? "bg-danger-soft text-danger" : "bg-warn-soft text-warn")}>
            <AlertTriangle className="size-4 shrink-0" />
            <span className="min-w-0 flex-1">
              <b className="font-semibold">Stale index</b>: {summary.stale_reasons.join(", ")}.{" "}
              {summary.reindex_required ? "Re-index before chatting." : "Chat still uses the existing index."}
            </span>
            <Button size="sm" onClick={reindex}>
              <RefreshCw className="size-3.5" /> Re-index now
            </Button>
          </div>
        )}
        {jobRunning && tab === "chat" && (
          <button onClick={() => onTab("index")} className="mt-3 flex w-full items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-left text-sm text-ink-2 hover:text-ink">
            <Loader2 className="size-4 animate-spin text-accent" />
            <span className="flex-1 truncate">{snapshot?.message ?? "Working…"}</span>
            <span className="text-xs">View progress →</span>
          </button>
        )}
        {actionError && <ErrorNote className="mt-3" message={actionError} />}

        <div role="tablist" className="mt-3 flex gap-1">
          {(
            [
              ["chat", "Chat", MessageSquare],
              ["index", "Sources & index", Layers],
            ] as const
          ).map(([key, label, Icon]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => onTab(key)}
              className={cx(
                "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition",
                tab === key ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink",
              )}
            >
              <Icon className="size-4" /> {label}
              {key === "index" && jobRunning && <span className="size-1.5 rounded-full bg-accent" />}
            </button>
          ))}
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {tab === "chat" ? (
          <ChatView
            collection={summary}
            store={store}
            settings={settings}
            labMode={labMode}
            onCloseLab={() => onLabMode(false)}
            disabledReason={disabledReason}
          />
        ) : (
          <div className="scroll-thin h-full overflow-y-auto">
            <div className="mx-auto max-w-4xl space-y-6 px-4 py-6 sm:px-6">
              {jobId && (
                <div>
                  <PipelineView snapshot={snapshot} chunkSize={summary.indexed_with?.chunk_size ?? settings?.chunk_size} />
                  {streamError && <ErrorNote className="mt-3" message={streamError} />}
                  {snapshot?.stage === "done" && summary.chunk_count > 0 && (
                    <div className="mt-3 flex justify-end">
                      <Button variant="primary" onClick={() => onTab("chat")}>
                        Start chatting <ArrowRight className="size-4" />
                      </Button>
                    </div>
                  )}
                </div>
              )}
              <AddSources collectionId={summary.id} disabled={jobRunning} onStarted={onJobStarted} defaultOpen={!summary.source_count && !jobId} />
              <SourcesTable detail={detail} error={detailError} />
            </div>
          </div>
        )}
      </div>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete knowledge base?">
        <DeleteConfirm
          name={summary.name}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={async () => {
            await api.deleteCollection(summary.id);
            setConfirmDelete(false);
            onDeleted();
          }}
        />
      </Modal>
    </div>
  );
}

function AddSources({ collectionId, disabled, onStarted, defaultOpen }: { collectionId: string; disabled: boolean; onStarted: (s: JobStarted) => void; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="rounded-2xl border border-line bg-card">
      <div className="flex items-center gap-3 px-5 py-4">
        <div className="flex-1">
          <h2 className="font-display font-semibold">Add sources</h2>
          <p className="text-sm text-muted">New files are chunked with this collection&apos;s settings and added to its index.</p>
        </div>
        {!open && (
          <Button size="sm" onClick={() => setOpen(true)} disabled={disabled}>
            <Plus className="size-4" /> Add
          </Button>
        )}
      </div>
      {open && (
        <div className="border-t border-line px-5 py-5">
          <IngestPanel
            mode="add"
            busy={busy}
            error={error}
            onCancel={() => setOpen(false)}
            onSubmit={async ({ files, urls }) => {
              setBusy(true);
              setError(null);
              try {
                onStarted(await api.addSources(collectionId, files, urls));
                setOpen(false);
              } catch (err) {
                setError(err instanceof ApiError ? err.message : "Upload failed");
              } finally {
                setBusy(false);
              }
            }}
          />
        </div>
      )}
    </section>
  );
}

function SourcesTable({ detail, error }: { detail: CollectionDetail | null; error: string | null }) {
  if (error) return <ErrorNote message={error} />;
  if (!detail) return <Skeleton className="h-40 rounded-2xl" />;
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-card">
      <div className="flex flex-wrap items-baseline gap-x-3 px-5 py-4">
        <h2 className="font-display font-semibold">Indexed sources</h2>
        {detail.indexed_with && (
          <span className="font-mono text-[11px] text-muted">
            {detail.indexed_with.embedding_model} · size {detail.indexed_with.chunk_size} · overlap {detail.indexed_with.chunk_overlap}
          </span>
        )}
      </div>
      {detail.sources.length === 0 ? (
        <p className="border-t border-line px-5 py-6 text-sm text-muted">No sources indexed yet.</p>
      ) : (
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[560px] table-fixed text-sm">
            <thead className="bg-sunken/60 text-left font-mono text-[10px] tracking-widest text-muted uppercase">
              <tr>
                <th className="px-5 py-2 font-medium">Source</th>
                <th className="w-20 px-3 py-2 text-right font-medium">Pages</th>
                <th className="w-24 px-3 py-2 text-right font-medium">Chars</th>
                <th className="w-20 px-3 py-2 text-right font-medium">Chunks</th>
                <th className="w-32 px-5 py-2 text-right font-medium">Added</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {detail.sources.map((s) => (
                <tr key={s.source_id}>
                  <td className="px-5 py-2.5">
                    <div className="flex items-center gap-2">
                      {s.kind === "url" ? <Globe className="size-4 shrink-0 text-embed" /> : <FileText className="size-4 shrink-0 text-load" />}
                      <span className="truncate" title={s.kind === "url" ? s.original : s.name}>
                        {s.name}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">{s.pages}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">{fmtChars(s.characters)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs tabular-nums">{s.chunks}</td>
                  <td className="px-5 py-2.5 text-right text-xs whitespace-nowrap text-muted">{fmtRelative(s.added_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex gap-2 border-t border-line px-5 py-3 font-mono text-[11px] text-muted">
        <Badge>{fmtInt(detail.chunk_count)} chunks</Badge>
        <span className="self-center">created {fmtRelative(detail.created_at)}</span>
      </div>
    </section>
  );
}

function DeleteConfirm({ name, onCancel, onConfirm }: { name: string; onCancel: () => void; onConfirm: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">
        This permanently removes <b className="font-medium text-ink">{name}</b>: its uploaded files, extracted text and vector index.
      </p>
      {error && <ErrorNote message={error} />}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button
          variant="danger"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onConfirm();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "Delete failed");
              setBusy(false);
            }
          }}
        >
          <Trash2 className="size-4" /> Delete
        </Button>
      </div>
    </div>
  );
}
